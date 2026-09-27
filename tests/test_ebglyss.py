"""Ebglyss AK Medicaid criteria and catalog integration from the 2026 PDF."""

from __future__ import annotations

import gzip
import json
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate, find_alternatives  # noqa: E402
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog  # noqa: E402


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/ebglyss.json").read_text())


def _base(**extra):
    facts = {
        "indication": "atopic_dermatitis",
        "age_years": 30,
        "prescriber_specialty": "dermatologist",
        "ad_bsa_severity_documented": True,
        "ad_topical_failures": [
            "medium_high_tcs_adult_or_low_tcs_pediatric",
            "topical_calcineurin_inhibitor",
        ],
        "not_used_with_another_biologic": True,
    }
    facts.update(extra)
    return facts


def _assert_fail(clause, **extra):
    result = evaluate(load_pack(), _base(**extra))
    assert result.decision == "fail", result
    assert clause in {c["id"] for c in result.failed_clauses}, result


def test_encoding_status_partial_and_pdl_non_preferred():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert pack["pdl_status"] == "non_preferred"
    assert pack["drug"] == {
        "name": "Ebglyss", "generic_name": "lebrikizumab-lbkz",
        "therapeutic_class": "immunomodulators",
    }
    assert len(pack["criteria"]) == 5
    assert pack["max_units"]["quantity"] is None


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("ebglyss")
    assert detail
    field = next(f for f in detail["fact_fields"] if f["key"] == "indication")
    assert field["type"] == "select"
    assert field["option_source"] == "fact_ui"
    assert [o["value"] for o in field["options"]] == ["atopic_dermatitis"]
    for invalid in ["yes", "no", "unknown", "asthma"]:
        _assert_fail("indication_fda_labeled", indication=invalid)


def test_fact_ui_selects_and_multis_only():
    pack = load_pack()
    detail = drug_detail("ebglyss")
    assert detail
    assert {f["key"] for f in detail["fact_fields"]} == set(_base())
    for field in detail["fact_fields"]:
        assert field["type"] in ("select", "multi"), field
        assert field.get("free_text") is not True
        assert field.get("options"), field
    assert pack["fact_ui"]["age_years"]["option_style"] == "age_bands"
    assert pack["fact_ui"]["ad_topical_failures"]["type"] == "multi"
    dup = get_rule_pack("dupixent")[1]
    assert [o["value"] for o in pack["fact_ui"]["ad_topical_failures"]["options"]] == [
        o["value"] for o in dup["fact_ui"]["ad_topical_failures"]["options"]
    ]


def test_ad_pass_age_boundary_specialties_and_topical_pairs():
    for specialty in ["allergist", "immunologist", "dermatologist"]:
        for pair in combinations([
            "medium_high_tcs_adult_or_low_tcs_pediatric",
            "topical_calcineurin_inhibitor", "pde4_inhibitor",
        ], 2):
            result = evaluate(load_pack(), _base(
                age_years=12, prescriber_specialty=specialty,
                ad_topical_failures=list(pair),
            ))
            assert result.decision == "pass", result
    assert evaluate(load_pack(), _base(
        ad_bsa_severity_documented=True, not_used_with_another_biologic=True,
    )).decision == "pass"


def test_ad_fail_age_under_12():
    _assert_fail("fda_labeled_age_for_indication", age_years=11)


def test_ad_fail_specialty_primary_care():
    _assert_fail("prescriber_specialty_for_indication", prescriber_specialty="primary_care")


def test_ad_fail_insufficient_topicals():
    for values in [[], ["topical_calcineurin_inhibitor"], ["pde4_inhibitor", "unknown"]]:
        _assert_fail("ad_documentation_and_step_therapy", ad_topical_failures=values)


def test_ad_fail_missing_bsa_documentation():
    _assert_fail("ad_documentation_and_step_therapy", ad_bsa_severity_documented=False)


def test_unanswered_bsa_needs_info():
    facts = _base()
    del facts["ad_bsa_severity_documented"]
    result = evaluate(load_pack(), facts)
    assert result.decision == "need_info"
    assert "ad_bsa_severity_documented" in result.missing_facts


def test_ad_fail_concomitant_biologic():
    _assert_fail("not_concomitant_biologic", not_used_with_another_biologic=False)


def test_catalog_and_mirrors_load_ebglyss_as_partial():
    base = ROOT / "data/alaska/parsed"
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    assert catalog["ebglyss"] == pack
    assert catalog["ebglyss"]["encoding_status"] == "partial"
    assert get_rule_pack("ebglyss") == ("ebglyss", pack)
    assert drug_detail("ebglyss")
    assert json.loads((base / "rule_packs/ebglyss.json").read_text()) == pack
    with gzip.open(base / "rule_packs_all.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream) == catalog
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 152
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 46


def test_bidirectional_alternatives_evaluate():
    catalog = load_rule_pack_catalog()
    assert load_pack()["alternatives"] == ["adbry", "dupixent"]
    base = ROOT / "data/alaska/parsed"
    for slug, expected in [
        ("adbry", {"dupixent", "ebglyss"}),
        ("dupixent", {"adbry", "ebglyss", "xolair", "fasenra", "nucala", "cinqair", "tezspire"}),
    ]:
        for path in [f"{slug}.json", f"rule_packs/{slug}.json"]:
            peer = json.loads((base / path).read_text())
            assert set(peer["alternatives"]) == expected
            assert evaluate(peer, _base()).decision == "pass"
            alts = find_alternatives(peer, _base(), catalog)
            assert any(a["rule_id"] == "ebglyss" and a["verification"] == "evaluate_pass"
                       for a in alts), alts
    alts = find_alternatives(load_pack(), _base(), catalog)
    assert {a["rule_id"] for a in alts if a["verification"] == "evaluate_pass"} == {"adbry", "dupixent"}
    result = check(load_pack(), _base(age_years=11), catalog)
    assert result.decision == "fail"
    assert {a["rule_id"] for a in result.alternatives if a["verification"] == "evaluate_pass"} == {"dupixent"}
    assert find_alternatives(load_pack(), _base(not_used_with_another_biologic=False), catalog) == []


def test_source_and_attestation_only_limits():
    pack = load_pack()
    assert pack["source"]["effective_date"] == "2026-03-01"
    assert pack["source"]["citation"] == "https://health.alaska.gov/media/gdcjebpg/ebglyss_criteria.pdf"
    assert "inferred_required_facts" not in pack
    assert pack["fact_ui"]["indication"]["options"][0]["label"] == (
        "Moderate-to-severe atopic dermatitis (≥12 years, ≥40 kg)"
    )
    # No weight or quantity fact is silently promoted into a predicate.
    assert {fact for clause in pack["criteria"] for fact in clause["required_facts"]} == set(_base())
    assert not any("weight" in json.dumps(c["predicate"]) or "quantity" in json.dumps(c["predicate"])
                   for c in pack["criteria"])
    notes = " ".join(pack["notes"])
    for text in ["12/22/2025", "01/16/2026", "Weight ≥40 kg", "attestation-only", "not predicated",
                 "live vaccines", "helminth", "eye symptoms", "exactly age 18"]:
        assert text in notes
    for text in ["six 250 mg", "two 250 mg", "one 250 mg", "up to 3 months", "up to 12 months"]:
        assert text in pack["max_units"]["notes"]


def test_full_catalog_and_status_mirrors():
    base = ROOT / "data/alaska/parsed"
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (base / "rule_packs").glob("*.json")}
    assert (base / "ebglyss.json").read_bytes() == (base / "rule_packs/ebglyss.json").read_bytes()
    status = json.loads((base / "ENCODING_STATUS.json").read_text())
    assert status["encoding_partial"] == 152
    assert status["encoding_text_only"] == 46
    assert status["partial_slugs"] == sorted(s for s, p in catalog.items() if p["encoding_status"] == "partial")
    assert "ebglyss" in status["partial_slugs"]
    for suffix in ["json", "md"]:
        assert (base / f"ENCODING_STATUS.{suffix}").read_bytes() == (base.parent / f"ENCODING_STATUS.{suffix}").read_bytes()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ebglyss tests ok")
