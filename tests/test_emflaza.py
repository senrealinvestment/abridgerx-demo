"""Emflaza AK Medicaid Version 1 criteria and catalog integration."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import evaluate
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog
from ui.app import _coerce_patient


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/emflaza.json").read_text())


def _base(**extra):
    facts = {
        "indication": "dmd",
        "age_years": 2.0,
        "prescriber_specialty": "neurologist",
        "dmd_documented_by_dystrophin_gene": True,
        "prednisone_step": "trial_failure_6mo",
        "not_concurrent_live_vaccinations": True,
    }
    facts.update(extra)
    return facts


def _assert_fail(clause, **extra):
    result = evaluate(load_pack(), _base(**extra))
    assert result.decision == "fail", result
    assert {c["id"] for c in result.failed_clauses} == {clause}, result


def test_metadata_and_source_criteria():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert pack["pdl_status"] == "unknown"
    assert pack["drug"] == {"name": "Emflaza", "generic_name": "deflazacort",
                            "therapeutic_class": "corticosteroids"}
    assert pack["source"]["effective_date"] == "2019-11-20"
    assert pack["source"]["citation"] == "https://health.alaska.gov/media/fqpa0ykl/20199emflaza_criteria_approved_2019.pdf"
    assert pack["source"]["criteria_pdf"] == "data/alaska/raw/20199emflaza_criteria_approved_2019.pdf"
    assert "inferred_required_facts" not in pack
    assert len(pack["criteria"]) == 6
    assert {f for c in pack["criteria"] for f in c["required_facts"]} == set(_base())
    assert pack["max_units"] == {
        "quantity": None, "days_supply": None,
        "notes": "Up to 0.9 mg/kg/day rounded to nearest tablet strength (6, 18, 30, 36 mg). Attestation only.",
    }
    notes = " ".join(pack["notes"])
    for text in ["8/13/2019", "9/20/2019", "11/20/2019", "up to 30 days",
                 "up to 12 months", "endocrine", "cardiovascular", "renal",
                 "infection", "mood", "bone mineral density", "manual review"]:
        assert text in notes, text


def test_closed_indication_and_selects_only():
    detail = drug_detail("emflaza")
    assert detail and detail["can_evaluate"]
    fields = {f["key"]: f for f in detail["fact_fields"]}
    assert set(fields) == set(_base()) == set(load_pack()["fact_ui"])
    for field in fields.values():
        assert field["type"] == "select"
        assert field["option_source"] == "fact_ui"
        assert field.get("free_text") is not True
        assert field["options"]
    assert fields["indication"]["options"] == [{
        "value": "dmd", "label": "Duchenne muscular dystrophy (DMD)",
    }]
    assert fields["age_years"]["options"] == [
        {"value": "0", "label": "Under 2"},
        {"value": "2", "label": "2 years or older"},
    ]
    for invalid in ["yes", "no", "unknown", True, False, "other"]:
        _assert_fail("indication_fda_labeled", indication=invalid)


def test_pass_and_age_boundary():
    for age in [2.0, 3.0, 18.0]:
        assert evaluate(load_pack(), _base(age_years=age)).decision == "pass"
    for age in [0.0, 1.0, 1.99]:
        _assert_fail("minimum_age", age_years=age)


def test_specialty_and_prednisone_routes():
    for specialty in ["neurologist", "dmd_specialist"]:
        for step in ["trial_failure_6mo", "contraindication", "significant_adverse_effects"]:
            assert evaluate(load_pack(), _base(prescriber_specialty=specialty,
                                              prednisone_step=step)).decision == "pass"
    for specialty in ["primary_care", "other"]:
        _assert_fail("prescriber_specialty", prescriber_specialty=specialty)
    _assert_fail("prednisone_step", prednisone_step="none")


def test_fail_diagnosis_and_live_vaccinations():
    _assert_fail("dmd_documented_by_dystrophin_gene", dmd_documented_by_dystrophin_gene=False)
    _assert_fail("not_concurrent_live_vaccinations", not_concurrent_live_vaccinations=False)


def test_every_ui_option_and_coercion():
    pack = load_pack()
    facts = {key: field["options"][0]["value"] for key, field in pack["fact_ui"].items()}
    facts["age_years"] = "2"
    assert _coerce_patient(facts) == _base()
    passing = {
        "age_years": {"2"}, "prescriber_specialty": {"neurologist", "dmd_specialist"},
        "prednisone_step": {"trial_failure_6mo", "contraindication", "significant_adverse_effects"},
        "indication": {"dmd"},
    }
    for fact, field in pack["fact_ui"].items():
        for option in field["options"]:
            value = option["value"]
            result = evaluate(pack, _coerce_patient(dict(facts, **{fact: value})))
            expected = "pass" if value in passing.get(fact, {"yes"}) else "fail"
            assert result.decision == expected, (fact, value, result)


def test_missing_facts_need_info():
    for fact in _base():
        facts = _base()
        del facts[fact]
        result = evaluate(load_pack(), facts)
        assert result.decision == "need_info", result
        assert result.missing_facts == [fact], result
    result = evaluate(load_pack(), {})
    assert result.decision == "need_info"
    assert set(result.missing_facts) == set(_base())


def test_catalog_mirrors_and_status_load():
    base = ROOT / "data/alaska/parsed"
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    assert catalog["emflaza"] == pack
    assert get_rule_pack("emflaza") == ("emflaza", pack)
    assert (base / "rule_packs/emflaza.json").read_bytes() == (base / "emflaza.json").read_bytes()
    assert catalog == {
        path.stem: json.loads(path.read_text())
        for path in (base / "rule_packs").glob("*.json")
    }
    with gzip.open(base / "rule_packs_all.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 37
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 161
    assert pack["alternatives"] == []
    status = json.loads((base / "ENCODING_STATUS.json").read_text())
    assert status["encoding_partial"] == 37
    assert status["encoding_text_only"] == 161
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
    print("emflaza tests ok")
