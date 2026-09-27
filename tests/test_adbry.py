"""Adbry AK Medicaid criteria and catalog integration from the 2024 PDF."""

from __future__ import annotations

import gzip
import json
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate  # noqa: E402
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog  # noqa: E402


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/adbry.json").read_text())


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


def test_encoding_status_partial_and_pdl_preferred():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert pack["pdl_status"] == "preferred"
    assert pack["drug"] == {
        "name": "Adbry", "generic_name": "tralokinumab-ldrm",
        "therapeutic_class": "immunomodulators",
    }
    assert len(pack["criteria"]) == 5
    assert pack["max_units"]["quantity"] is None


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("adbry")
    assert detail
    field = next(f for f in detail["fact_fields"] if f["key"] == "indication")
    assert field["type"] == "select"
    assert field["option_source"] == "fact_ui"
    assert [o["value"] for o in field["options"]] == ["atopic_dermatitis"]
    for invalid in ["yes", "no", "unknown", "asthma"]:
        _assert_fail("indication_fda_labeled", indication=invalid)


def test_fact_ui_selects_and_multis_only():
    pack = load_pack()
    detail = drug_detail("adbry")
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


def test_catalog_and_mirrors_load_adbry_as_partial():
    base = ROOT / "data/alaska/parsed"
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    assert catalog["adbry"] == pack
    assert catalog["adbry"]["encoding_status"] == "partial"
    assert get_rule_pack("adbry") == ("adbry", pack)
    assert drug_detail("adbry")
    assert json.loads((base / "rule_packs/adbry.json").read_text()) == pack
    with gzip.open(base / "rule_packs_all.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream) == catalog
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 86
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 112


def test_bidirectional_alternatives_and_dupixent_evaluate_pass():
    catalog = load_rule_pack_catalog()
    assert load_pack()["alternatives"] == ["dupixent", "ebglyss"]
    for path in ["dupixent.json", "rule_packs/dupixent.json"]:
        dup = json.loads((ROOT / "data/alaska/parsed" / path).read_text())
        assert set(dup["alternatives"]) == {
            "adbry", "ebglyss", "xolair", "fasenra", "nucala", "cinqair", "tezspire",
        }
    result = check(load_pack(), _base(age_years=11), catalog)
    assert result.decision == "fail"
    assert any(a.get("rule_id") == "dupixent" and a.get("verification") == "evaluate_pass"
               for a in result.alternatives), result.alternatives


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("adbry tests ok")
