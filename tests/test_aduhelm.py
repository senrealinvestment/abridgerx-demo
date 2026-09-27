"""Aduhelm AK Medicaid Version 1 criteria and catalog integration."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import evaluate  # noqa: E402
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog  # noqa: E402


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/aduhelm.json").read_text())


def _base(**extra):
    facts = {
        "indication": "alzheimers_disease_mci_or_mild_dementia",
        "age_years": 50.0,
        "prescriber_specialty": "neurologist",
        "amyloid_confirmation": "pet_scan",
        "mri_safety_criteria_met": True,
        "objective_cognitive_impairment": True,
        "cdr_global_score": "0.5",
        "mmse_score": "gte_24",
        "other_dementia_causes_ruled_out": True,
        "not_on_disallowed_blood_thinners": True,
        "no_recent_cns_bleed_or_cerebrovascular_abnormality": True,
        "no_significant_systemic_illness_or_infection_30d": True,
        "no_unstable_cardiac_history_1y": True,
    }
    facts.update(extra)
    return facts


def _assert_fail(clause, **extra):
    result = evaluate(load_pack(), _base(**extra))
    assert result.decision == "fail", result
    assert {c["id"] for c in result.failed_clauses} == {clause}, result


def test_encoding_partial_and_pdl_non_preferred():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert pack["pdl_status"] == "non_preferred"
    assert pack["drug"] == {
        "name": "Aduhelm", "generic_name": "aducanumab-avwa",
        "therapeutic_class": "alzheimers-agents",
    }
    assert pack["source"]["effective_date"] == "2021-11-01"
    assert pack["source"]["citation"] == "https://health.alaska.gov/media/zmhj3izn/202109-aduhelm_criteria_2021.pdf"
    assert len(pack["criteria"]) == 13
    assert "inferred_required_facts" not in pack
    assert pack["max_units"]["quantity"] is None
    for dose in [1, 3, 6, 10]:
        assert f"{dose} mg/kg" in pack["max_units"]["notes"]
    for text in ["7/16/2021", "9/17/21", "up to 3 months", "up to 6 months", "7th and 12th", "ARIA"]:
        assert any(text in note for note in pack["notes"]), text


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("aduhelm")
    assert detail
    field = next(f for f in detail["fact_fields"] if f["key"] == "indication")
    assert field["options"] == [{
        "value": "alzheimers_disease_mci_or_mild_dementia",
        "label": "Alzheimer's disease (mild cognitive impairment or mild dementia stage)",
    }]
    for invalid in ["yes", "no", "unknown", "alzheimers_disease", "severe_dementia"]:
        _assert_fail("indication_fda_labeled", indication=invalid)


def test_selects_only_and_custom_age_options():
    pack = load_pack()
    detail = drug_detail("aduhelm")
    assert detail
    assert set(pack["fact_ui"]) == set(_base())
    fields = {f["key"]: f for f in detail["fact_fields"]}
    assert set(fields) == set(_base())
    for field in fields.values():
        assert field["type"] == "select", field
        assert field.get("free_text") is not True
        assert field["option_source"] == "fact_ui"
        assert field["options"]
    assert fields["age_years"]["options"] == [
        {"value": "0", "label": "Under 50 years"},
        {"value": "50", "label": "50 years or older"},
    ]
    # Exercise authored option values with the UI's bool/age-only conversion.
    facts = {key: field["options"][0]["value"] for key, field in fields.items()}
    facts["age_years"] = "50"
    facts = {key: (float(value) if key == "age_years" else
                   True if value == "yes" else False if value == "no" else value)
             for key, value in facts.items()}
    assert evaluate(pack, facts).decision == "pass"


def test_pass_both_amyloid_paths():
    for amyloid in ["pet_scan", "csf_testing"]:
        result = evaluate(load_pack(), _base(amyloid_confirmation=amyloid))
        assert result.decision == "pass", result
        assert not result.missing_facts


def test_fail_age_under_50():
    for age in [0.0, 49.0, 49.9]:
        _assert_fail("minimum_age", age_years=age)


def test_fail_non_neurologist():
    for specialty in ["primary_care", "geriatrician", "psychiatrist", "other"]:
        _assert_fail("prescriber_specialty", prescriber_specialty=specialty)


def test_fail_neither_amyloid():
    _assert_fail("amyloid_confirmation", amyloid_confirmation="neither")


def test_fail_cdr_other_and_mmse_below_24():
    _assert_fail("cdr_global_score", cdr_global_score="other")
    _assert_fail("mmse_score", mmse_score="lt_24")


def test_fail_each_approval_attestation():
    for fact in ["mri_safety_criteria_met", "objective_cognitive_impairment",
                 "other_dementia_causes_ruled_out"]:
        _assert_fail(fact, **{fact: False})


def test_fail_each_denial_fact():
    for fact in ["not_on_disallowed_blood_thinners",
                 "no_recent_cns_bleed_or_cerebrovascular_abnormality",
                 "no_significant_systemic_illness_or_infection_30d",
                 "no_unstable_cardiac_history_1y"]:
        _assert_fail(fact, **{fact: False})


def test_missing_facts_need_info():
    for fact in _base():
        facts = _base()
        del facts[fact]
        result = evaluate(load_pack(), facts)
        assert result.decision == "need_info", result
        assert result.missing_facts == [fact], result
    assert set(evaluate(load_pack(), {}).missing_facts) == set(_base())


def test_catalog_mirrors_and_status_load():
    base = ROOT / "data/alaska/parsed"
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    assert catalog["aduhelm"] == pack
    assert get_rule_pack("aduhelm") == ("aduhelm", pack)
    assert (base / "aduhelm.json").read_bytes() == (base / "rule_packs/aduhelm.json").read_bytes()
    assert catalog == {path.stem: json.loads(path.read_text())
                       for path in (base / "rule_packs").glob("*.json")}
    with gzip.open(base / "rule_packs_all.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 172
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 26
    assert pack["alternatives"] == ["leqembi", "kisunla"]
    for slug in ["kisunla"]:
        assert catalog[slug]["encoding_status"] == "partial"
    status = json.loads((base / "ENCODING_STATUS.json").read_text())
    assert status["encoding_partial"] == 172
    assert status["encoding_text_only"] == 26
    assert status["partial_slugs"] == sorted(
        slug for slug, p in catalog.items() if p["encoding_status"] == "partial"
    )
    assert json.loads((base.parent / "ENCODING_STATUS.json").read_text()) == status
    assert (base.parent / "ENCODING_STATUS.md").read_text() == (base / "ENCODING_STATUS.md").read_text()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("aduhelm tests ok")
