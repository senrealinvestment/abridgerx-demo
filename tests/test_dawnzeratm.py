"""Dawnzera AK Medicaid Version 1 criteria and catalog integration."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog
from ui.app import _coerce_patient


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/dawnzeratm.json").read_text())


def _base(**extra):
    facts = {
        "indication": "hae_prophylaxis_c1_inh_deficiency_type_1_or_2",
        "age_years": 12.0,
        "prescriber_specialty": "immunologist",
        "angioedema_linked_meds_evaluated": True,
        "not_combined_with_other_hae_prophylaxis": True,
        "hae_attacks_ge_3_moderate_severe_per_month": True,
        "failed_or_contraindicated_two_preferred_hae_prophylaxis_different_classes": "two_preferred_different_classes_failed_or_contraindicated",
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
    assert pack["drug"] == {
        "name": "Dawnzera", "generic_name": "donidalorsen",
        "therapeutic_class": "hae-treatments",
    }
    assert pack["source"]["effective_date"] == "2026-01-01"
    assert pack["source"]["citation"] == "https://health.alaska.gov/media/jbmaasjr/dawnzera_criteria.pdf"
    assert pack["source"]["criteria_pdf"] == "data/alaska/raw/dawnzera_criteria.pdf"
    assert "inferred_required_facts" not in pack
    assert len(pack["criteria"]) == 7
    predicates = {c["predicate"]["fact"]: c["predicate"] for c in pack["criteria"]}
    assert set(predicates) == set(_base())
    assert predicates["age_years"] == {"op": "gte", "fact": "age_years", "value": 12}
    assert predicates["prescriber_specialty"] == {
        "op": "in", "fact": "prescriber_specialty", "values": ["allergist", "immunologist"],
    }
    assert pack["max_units"]["quantity"] is None
    notes = " ".join(pack["notes"])
    for text in ["10/10/2025", "11/21/2025", "01/01/2026", "up to 3 months",
                 "up to 1 year", "80mg", "28 days", "pregnancy",
                 "breastfeeding", "injection site reactions", "upper respiratory tract infection", "urinary tract infection", "abdominal discomfort",
                 "no duplicate diagnosis or prophylaxis-only attestation"]:
        assert text in notes, text


def test_closed_indication_and_selects_only():
    detail = drug_detail("dawnzeratm")
    assert detail and detail["can_evaluate"]
    fields = {f["key"]: f for f in detail["fact_fields"]}
    assert set(fields) == set(_base()) == set(load_pack()["fact_ui"])
    for field in fields.values():
        assert field["type"] == "select"
        assert field["option_source"] == "fact_ui"
        assert field.get("free_text") is not True
        assert field["options"]
    assert fields["indication"]["options"] == [{
        "value": "hae_prophylaxis_c1_inh_deficiency_type_1_or_2",
        "label": "Prophylaxis to prevent HAE attacks due to C1-esterase inhibitor deficiency (HAE-C1-INH) type 1 or 2",
    }]
    assert fields["age_years"]["options"] == [
        {"value": "0", "label": "Under 12 years"},
        {"value": "12", "label": "12 years or older"},
    ]
    for invalid in ["yes", "no", "unknown", True, False, "hae", "hae_prophylaxis", "hae_acute_attacks", "hae_type_3"]:
        _assert_fail("indication_fda_labeled", indication=invalid)
    for fact, value in _base().items():
        if value is True:
            assert fields[fact]["options"] == [
                {"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"},
            ]


def test_pass_and_age_boundary():
    for age in [12.0, 18.0, 65.0]:
        result = evaluate(load_pack(), _base(age_years=age))
        assert result.decision == "pass", result
        assert not result.missing_facts
    for age in [0.0, 11.0, 11.9]:
        _assert_fail("minimum_age", age_years=age)


def test_specialty():
    for specialty in ["allergist", "immunologist"]:
        assert evaluate(load_pack(), _base(prescriber_specialty=specialty)).decision == "pass"
    for specialty in ["primary_care", "other", "hematologist"]:
        _assert_fail("prescriber_specialty", prescriber_specialty=specialty)


def test_fail_each_approval_and_denial_attestation():
    for fact, value in _base().items():
        if value is True:
            _assert_fail(fact, **{fact: False})


def test_preferred_prophylaxis_step():
    key = "failed_or_contraindicated_two_preferred_hae_prophylaxis_different_classes"
    assert [o["value"] for o in load_pack()["fact_ui"][key]["options"]] == [
        "two_preferred_different_classes_failed_or_contraindicated", "not_met",
    ]
    for invalid in ["not_met", "yes", True, "failed_acute_hae_treatment", "failed_or_contraindicated_c1_inh_or_plasma_kallikrein_inhibitor", "two_preferred_same_class"]:
        _assert_fail(key, **{key: invalid})


def test_ui_coercion():
    facts = {key: field["options"][0]["value"]
             for key, field in load_pack()["fact_ui"].items()}
    facts["age_years"] = "12"
    assert evaluate(load_pack(), _coerce_patient(facts)).decision == "pass"
    for fact, value in _base().items():
        if value is True:
            assert evaluate(load_pack(), _coerce_patient(dict(facts, **{fact: "no"}))).decision == "fail"
    assert evaluate(load_pack(), _coerce_patient(dict(facts, age_years="0"))).decision == "fail"


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
    assert catalog["dawnzeratm"] == pack
    assert get_rule_pack("dawnzeratm") == ("dawnzeratm", pack)
    assert json.loads((base / "rule_packs/dawnzeratm.json").read_text()) == pack
    assert catalog == {
        path.stem: json.loads(path.read_text())
        for path in (base / "rule_packs").glob("*.json")
    }
    with gzip.open(base / "rule_packs_all.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 118
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 80
    assert pack["alternatives"] == ["andembry", "cinryze"]
    status = json.loads((base / "ENCODING_STATUS.json").read_text())
    assert status["next_candidate"] == 'voyxact'
    assert status["encoding_partial"] == 118
    assert status["encoding_text_only"] == 80
    assert status["partial_slugs"] == sorted(
        slug for slug, p in catalog.items() if p["encoding_status"] == "partial"
    )
    assert json.loads((base.parent / "ENCODING_STATUS.json").read_text()) == status
    assert (base.parent / "ENCODING_STATUS.md").read_text() == (base / "ENCODING_STATUS.md").read_text()


def test_distinct_steps_and_reciprocal_alternatives():
    dawnzera = load_pack()
    andembry = json.loads((ROOT / "data/alaska/parsed/andembry.json").read_text())
    dawnzera_key = "failed_or_contraindicated_two_preferred_hae_prophylaxis_different_classes"
    andembry_key = "failed_or_contraindicated_preferred_hae_prophylaxis"
    facts = _base()
    del facts[dawnzera_key]
    facts[andembry_key] = "failed_or_contraindicated_c1_inh_or_plasma_kallikrein_inhibitor"
    assert evaluate(andembry, facts).decision == "pass"
    result = evaluate(dawnzera, facts)
    assert result.decision == "need_info"
    assert result.missing_facts == [dawnzera_key]
    assert evaluate(andembry, _base()).missing_facts == [andembry_key]
    assert andembry["alternatives"] == ["cinryze", "dawnzeratm"]
    catalog = {"andembry": andembry, "dawnzeratm": dawnzera,
               "cinryze": json.loads((ROOT / "data/alaska/parsed/cinryze.json").read_text())}
    facts[dawnzera_key] = "not_met"
    result = check(dawnzera, facts, catalog)
    assert result.decision == "fail"
    assert [alt["rule_id"] for alt in result.alternatives if alt["verification"] == "evaluate_pass"] == ["andembry"]
    assert next(alt for alt in result.alternatives if alt["rule_id"] == "cinryze")["verification"] == "evaluate_need_info"
    facts[dawnzera_key] = _base()[dawnzera_key]
    facts[andembry_key] = "not_met"
    result = check(andembry, facts, catalog)
    assert result.decision == "fail"
    assert [alt["rule_id"] for alt in result.alternatives if alt["verification"] == "evaluate_pass"] == ["dawnzeratm"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("dawnzeratm tests ok")
