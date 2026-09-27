"""Empaveli AK Medicaid Version 1 criteria and catalog integration."""

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
    return json.loads((ROOT / "data/alaska/parsed/empaveli.json").read_text())


def _base(**extra):
    facts = {
        "indication": "pnh", "age_years": 18.0,
        "prescriber_specialty": "hematologist",
        "pnh_flow_cytometry_confirmed": True,
        "pnh_therapy_indication": "thrombotic_event_history",
        "baseline_ldh_and_hb_lt_10_5": True,
        "encapsulated_bacteria_vaccines_14d": True,
        "complement_inhibitor_combo_status": "not_combined",
        "no_unresolved_encapsulated_infection": True,
        "prescriber_rems_enrolled": True,
    }
    facts.update(extra)
    return facts


def _assert_fail(clause, **extra):
    result = evaluate(load_pack(), _base(**extra))
    assert result.decision == "fail", result
    assert {c["id"] for c in result.failed_clauses} == {clause}, result
    assert result.citations


def test_metadata_and_source_criteria():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert pack["pdl_status"] == "unknown"
    assert pack["drug"] == {"name": "Empaveli", "generic_name": "pegcetacoplan",
                            "therapeutic_class": "complement-inhibitor"}
    assert pack["source"]["effective_date"] == "2023-01-02"
    assert pack["source"]["citation"] == "https://health.alaska.gov/media/ybpntcwi/202211-empaveli_criteria_2022.pdf"
    assert pack["source"]["criteria_pdf"] == "data/alaska/raw/202211-empaveli_criteria_2022.pdf"
    assert "inferred_required_facts" not in pack
    assert len(pack["criteria"]) == 10
    assert {f for c in pack["criteria"] for f in c["required_facts"]} == set(_base())
    assert pack["max_units"]["quantity"] == 10
    assert pack["max_units"]["days_supply"] == 30
    notes = " ".join(pack["notes"])
    for text in ["10/10/2022", "11/18/2022", "1/2/2023", "6 months", "12 months",
                 "chart notes", "transfusion", "10 vials", "1080 mg", "every 3 days",
                 "J3490", "fatal infections", "REMS", "silica", "aPTT", "manual review"]:
        assert text in notes, text
    for clause in pack["criteria"]:
        pred = clause["predicate"]
        if pred["fact"] in {"baseline_ldh_and_hb_lt_10_5", "encapsulated_bacteria_vaccines_14d"}:
            assert pred == {"op": "eq", "fact": pred["fact"], "value": True}


def test_closed_indication_and_selects_only():
    detail = drug_detail("empaveli")
    assert detail and detail["can_evaluate"]
    fields = {f["key"]: f for f in detail["fact_fields"]}
    assert set(fields) == set(_base()) == set(load_pack()["fact_ui"])
    for field in fields.values():
        assert field["type"] == "select"
        assert field["option_source"] == "fact_ui"
        assert field.get("free_text") is not True
        assert field["options"]
    assert fields["indication"]["options"] == [{
        "value": "pnh", "label": "Paroxysmal nocturnal hemoglobinuria (PNH)",
    }]
    assert fields["age_years"]["options"] == [
        {"value": "0", "label": "Under 18"}, {"value": "18", "label": "18+"},
    ]
    for invalid in ["yes", "no", "unknown", True, False, "other"]:
        _assert_fail("indication_fda_labeled", indication=invalid)


def test_age_boundary_and_all_therapy_routes():
    for specialty in ["hematologist", "oncologist"]:
        for therapy in ["thrombotic_event_history", "organ_damage_chronic_hemolysis",
                        "transfusion_in_12mo", "high_ldh_with_symptoms"]:
            for combo in ["not_combined", "cross_titration_soliris_4wk"]:
                assert evaluate(load_pack(), _base(prescriber_specialty=specialty,
                    pnh_therapy_indication=therapy,
                    complement_inhibitor_combo_status=combo)).decision == "pass"
    for age in [18, 19, 80]:
        assert evaluate(load_pack(), _base(age_years=age)).decision == "pass"
    for age in [0, 17, 17.99]:
        _assert_fail("minimum_age", age_years=age)
    for specialty in ["primary_care", "other"]:
        _assert_fail("prescriber_specialty", prescriber_specialty=specialty)
    for therapy in ["none", "unknown"]:
        _assert_fail("pnh_therapy_indication", pnh_therapy_indication=therapy)
    for combo in ["combined_other", "cross_titration_ultomiris_4wk", "unknown"]:
        _assert_fail("complement_inhibitor_combo_status", complement_inhibitor_combo_status=combo)


def test_every_attestation_blocks_when_false():
    for fact, value in _base().items():
        if value is True:
            _assert_fail(fact, **{fact: False})


def test_every_ui_option_and_coercion():
    pack = load_pack()
    facts = {key: field["options"][0]["value"] for key, field in pack["fact_ui"].items()}
    facts["age_years"] = "18"
    assert _coerce_patient(facts) == _base()
    passing = {
        "age_years": {"18"}, "prescriber_specialty": {"hematologist", "oncologist"},
        "pnh_therapy_indication": {"thrombotic_event_history", "organ_damage_chronic_hemolysis",
                                   "transfusion_in_12mo", "high_ldh_with_symptoms"},
        "complement_inhibitor_combo_status": {"not_combined", "cross_titration_soliris_4wk"},
        "indication": {"pnh"},
    }
    for fact, field in pack["fact_ui"].items():
        for option in field["options"]:
            value = option["value"]
            result = evaluate(pack, _coerce_patient(dict(facts, **{fact: value})))
            expected = "pass" if value in passing.get(fact, {"yes"}) else "fail"
            assert result.decision == expected, (fact, value, result)
            if expected == "fail":
                clause = "minimum_age" if fact == "age_years" else fact
                assert {c["id"] for c in result.failed_clauses} == {clause}


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
    assert catalog["empaveli"] == pack
    assert get_rule_pack("empaveli") == ("empaveli", pack)
    assert (base / "rule_packs/empaveli.json").read_bytes() == (base / "empaveli.json").read_bytes()
    assert catalog == {
        path.stem: json.loads(path.read_text())
        for path in (base / "rule_packs").glob("*.json")
    }
    with gzip.open(base / "rule_packs_all.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 120
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 78
    assert pack["alternatives"] == ["soliris", "fabhalta"]
    status = json.loads((base / "ENCODING_STATUS.json").read_text())
    assert status["encoding_partial"] == 120
    assert status["encoding_text_only"] == 78
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
    print("empaveli tests ok")
