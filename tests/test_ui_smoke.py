"""Smoke test: load drug index + one evaluate check via UI loaders / API helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check  # noqa: E402
from ui.loaders import (  # noqa: E402
    drug_detail,
    get_rule_pack,
    load_drug_index,
    load_rule_pack_catalog,
    search_drugs,
)


def test_index_and_search():
    idx = load_drug_index()
    assert idx["payer"] == "alaska_medicaid"
    assert len(idx["drugs"]) > 1000
    hits = search_drugs("dupixent")
    assert hits, "expected Dupixent in search"
    assert any(h["slug"].startswith("dupixent") for h in hits)


def test_partial_pack_check():
    detail = drug_detail("dupixent")
    assert detail is not None
    assert detail["encoding_status"] == "partial"
    assert detail["can_evaluate"] is True
    by_key = {f["key"]: f for f in detail["fact_fields"]}
    assert "age_years" in by_key
    assert by_key["age_years"]["type"] == "select"
    assert by_key["age_years"]["options"]
    assert by_key["indication"]["type"] == "select"
    ind_opts = by_key["indication"]["options"]
    ind_vals = [(o["value"] if isinstance(o, dict) else o) for o in ind_opts]
    assert "asthma" in ind_vals
    assert "yes" not in ind_vals and "unknown" not in ind_vals
    assert by_key["prescriber_specialty"]["type"] == "select"
    spec_opts = by_key["prescriber_specialty"]["options"]
    spec_vals = [(o["value"] if isinstance(o, dict) else o) for o in spec_opts]
    assert "pulmonologist" in spec_vals

    # Age band "18+" maps to age_years=18 (band minimum) — adult asthma passes
    resolved = get_rule_pack("dupixent")
    assert resolved
    pack_slug, pack = resolved
    catalog = load_rule_pack_catalog()
    ok = check(
        pack,
        {
            "age_years": 18,  # band minimum for 18+
            "indication": "asthma",
            "prescriber_specialty": "pulmonologist",
            "asthma_phenotype": "eosinophilic_ge_150",
            "asthma_ics_laba_3mo": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert ok.decision == "pass", ok

    # Age band 1–5 (age_years=1) + asthma fails (>=6)
    fail = check(
        pack,
        {
            "age_years": 1,
            "indication": "asthma",
            "prescriber_specialty": "pulmonologist",
            "asthma_phenotype": "eosinophilic_ge_150",
            "asthma_ics_laba_3mo": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail.decision == "fail", fail

    # Xolair: adult CSU + allergist passes
    xdetail = drug_detail("xolair")
    assert xdetail and xdetail["can_evaluate"]
    xby = {f["key"]: f for f in xdetail["fact_fields"]}
    assert xby["indication"]["type"] == "select"
    assert xby["age_years"]["type"] == "select"
    assert xby["prescriber_specialty"]["type"] == "select"
    xresolved = get_rule_pack("xolair")
    assert xresolved
    _, xpack = xresolved
    xok = check(
        xpack,
        {
            "age_years": 18,
            "indication": "chronic_spontaneous_urticaria",
            "prescriber_specialty": "allergist",
            "csu_duration_and_frequency_met": True,
            "csu_failed_ltra_plus_antihistamine_2mo": True,
            "not_using_anti_il4_or_il5": True,
        },
        catalog,
    )
    assert xok.decision == "pass", xok
    xfail = check(
        xpack,
        {
            "age_years": 6,  # CSU needs >=12
            "indication": "chronic_spontaneous_urticaria",
            "prescriber_specialty": "allergist",
            "csu_duration_and_frequency_met": True,
            "csu_failed_ltra_plus_antihistamine_2mo": True,
            "not_using_anti_il4_or_il5": True,
        },
        catalog,
    )
    assert xfail.decision == "fail", xfail
    # Indication closed list never Yes/No/Unknown
    xvals = [
        (o["value"] if isinstance(o, dict) else o) for o in xby["indication"]["options"]
    ]
    assert set(xvals).isdisjoint({"yes", "no", "unknown"})
    assert "asthma" in xvals


def test_text_only_pack_surfaces_criteria():
    detail = drug_detail("skyrizi")
    assert detail is not None
    assert detail["encoding_status"] == "text_only"
    assert detail["can_evaluate"] is False
    assert detail["criteria_text"] and detail["criteria_text"].get("extracted_text")

    resolved = get_rule_pack("skyrizi")
    assert resolved
    _, pack = resolved
    result = check(pack, {"age_years": 40, "indication": "psoriasis"}, None)
    assert result.decision == "need_info"
    assert any("encoding_incomplete" in n for n in result.notes)


def test_no_free_text_fact_fields():
    """Every clinician fact control is select or multi — never free text."""
    for slug in ("dupixent", "xolair", "lyrica", "skyrizi"):
        detail = drug_detail(slug)
        assert detail, slug
        for f in detail["fact_fields"]:
            assert f.get("type") in ("select", "multi"), (slug, f)
            assert f.get("free_text") is not True, (slug, f)
            assert f.get("options"), (slug, f)


def test_lyrica_text_only_options_from_criteria():
    detail = drug_detail("lyrica")
    assert detail and detail["encoding_status"] == "text_only"
    by_key = {f["key"]: f for f in detail["fact_fields"]}
    assert "indication" in by_key
    ind = by_key["indication"]
    assert ind["type"] == "select"
    assert ind["option_source"] == "criteria_text"
    labels = " ".join(
        (o["label"] if isinstance(o, dict) else str(o)) for o in ind["options"]
    ).lower()
    assert "fibromyalgia" in labels or "neuralgia" in labels
    assert "prior_therapy_failures" in by_key
    ptf = by_key["prior_therapy_failures"]
    assert ptf["type"] == "multi"
    vals = " ".join(
        (o["value"] if isinstance(o, dict) else str(o)) for o in ptf["options"]
    ).lower()
    assert "gabapentin" in vals


def test_fail_and_text_only_alternatives():
    from ui.loaders import merge_alternatives, suggest_pdl_class_alternatives

    # Dupixent fail should surface PDL and/or evaluate alts via API helper path
    resolved = get_rule_pack("dupixent")
    assert resolved
    _, pack = resolved
    catalog = load_rule_pack_catalog()
    fail = check(
        pack,
        {
            "age_years": 1,
            "indication": "asthma",
            "prescriber_specialty": "pulmonologist",
            "asthma_phenotype": "eosinophilic_ge_150",
            "asthma_ics_laba_3mo": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail.decision == "fail"
    pdl = suggest_pdl_class_alternatives("dupixent", pack)
    merged = merge_alternatives(fail.alternatives, pdl)
    assert isinstance(merged, list)
    # Atopic dermatitis basket should yield preferred peers (or empty if index sparse)
    # Lyrica NEUROPATHIC PAIN has clear preferred peers (gabapentin, duloxetine, …)
    lyrica = drug_detail("lyrica")
    assert lyrica
    _, lpack = get_rule_pack("lyrica")
    lalts = suggest_pdl_class_alternatives("lyrica", lpack)
    assert lalts, "expected PDL preferred neuropathic peers for Lyrica"
    assert all(a.get("verification") == "pdl_preferred_same_class" for a in lalts)
    assert any("gabapentin" in (a.get("drug") or "").lower() or
               "gabapentin" in (a.get("generic_name") or "").lower()
               for a in lalts)


def test_indication_never_yes_no_unknown():
    """Global bug fix: indication must never fall back to Yes/No/Unknown."""
    from ui.loaders import build_fact_field

    # Synthetic pack with no indication options and no criteria text
    empty_pack = {
        "drug": {"name": "Synthetic"},
        "source": {
            "payer": "alaska_medicaid",
            "list": "x",
            "effective_date": "2020-01-01",
            "citation": "https://example.com",
        },
        "requires_pa": True,
        "encoding_status": "partial",
        "criteria": [
            {
                "id": "ind",
                "text": "has indication",
                "citation": "https://example.com",
                "required_facts": ["indication"],
                "predicate": {"op": "eq", "fact": "indication", "value": "x"},
            }
        ],
    }
    # eq-only still yields indication option "x" from predicates — strip by using empty criteria
    empty_pack["criteria"] = []
    field = build_fact_field("indication", empty_pack, None)
    assert field["type"] == "select"
    vals = [
        (o["value"] if isinstance(o, dict) else o) for o in (field.get("options") or [])
    ]
    assert "yes" not in vals
    assert "no" not in vals
    assert "unknown" not in vals
    assert field["option_source"] == "missing_indication_list"



if __name__ == "__main__":
    test_index_and_search()
    test_partial_pack_check()
    test_text_only_pack_surfaces_criteria()
    test_no_free_text_fact_fields()
    test_lyrica_text_only_options_from_criteria()
    test_fail_and_text_only_alternatives()
    test_indication_never_yes_no_unknown()
    print("ui smoke ok")
