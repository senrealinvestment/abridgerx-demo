"""Elevidys AK Medicaid Version 1 criteria and catalog integration."""

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
    return json.loads((ROOT / "data/alaska/parsed/elevidys.json").read_text())


def _base(**extra):
    facts = {
        "indication": "dmd_ambulatory_age_4_to_5",
        "age_years": 4.0,
        "prescriber_specialty": "neuromuscular_specialist",
        "dmd_diagnosis": True,
        "dmd_gene_mutation_confirmed": True,
        "exon_high_risk_myositis_monitoring": "not_applicable_no_exons_1_17_or_59_71",
        "no_exon_8_or_9_deletion": True,
        "currently_ambulatory": True,
        "anti_aavrh74_titer": "lt_1_400",
        "no_recent_dmd_antisense_oligo": True,
        "stable_corticosteroid_regimen": True,
        "baseline_lft_and_troponin_i_done": True,
        "no_clinically_significant_active_infection": True,
        "no_acute_liver_disease": True,
        "no_prior_dmd_gene_therapy": True,
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
        "name": "Elevidys", "generic_name": "delandistrogene moxeparvovec-rokl",
        "therapeutic_class": "cell-and-gene-therapy",
    }
    assert pack["source"]["effective_date"] == "2024-01-01"
    assert pack["source"]["citation"] == "https://health.alaska.gov/media/5abmvzjk/elevidys_criteria_2023.pdf"
    assert pack["source"]["criteria_pdf"] == "data/alaska/raw/elevidys_criteria_2023.pdf"
    assert "inferred_required_facts" not in pack
    assert len(pack["criteria"]) == 15
    assert {f for c in pack["criteria"] for f in c["required_facts"]} == set(_base())
    age = next(c["predicate"] for c in pack["criteria"] if c["id"] == "age_fda_labeled")
    assert age == {"op": "all", "args": [
        {"op": "gte", "fact": "age_years", "value": 4},
        {"op": "lte", "fact": "age_years", "value": 5},
    ]}
    assert pack["max_units"] == {
        "quantity": None, "days_supply": None,
        "notes": "One infusion per lifetime. HCPCS J3590. Attestation/manual review only; not a numeric predicate.",
    }
    notes = " ".join(pack["notes"])
    for text in ["09/21/2023", "11/17/2023", "01/1/2024", "initial approval 3 months",
                 "no reauthorization will be approved", "weekly for the first three months",
                 "weekly for one month", "immune-mediated myositis", "Myocarditis",
                 "accelerated approval", "confirmatory trial", "manual review"]:
        assert text in notes, text


def test_closed_indication_and_selects_only():
    detail = drug_detail("elevidys")
    assert detail and detail["can_evaluate"]
    fields = {f["key"]: f for f in detail["fact_fields"]}
    assert set(fields) == set(_base()) == set(load_pack()["fact_ui"])
    for field in fields.values():
        assert field["type"] == "select"
        assert field["option_source"] == "fact_ui"
        assert field.get("free_text") is not True
        assert field["options"]
    assert fields["indication"]["options"] == [{
        "value": "dmd_ambulatory_age_4_to_5",
        "label": "Duchenne muscular dystrophy (DMD) — ambulatory pediatric patients aged 4 through 5 years with confirmed DMD gene mutation",
    }]
    assert fields["age_years"]["options"] == [
        {"value": "0", "label": "Under 4 years"},
        {"value": "4", "label": "4 years"},
        {"value": "5", "label": "5 years"},
        {"value": "6", "label": "6 years or older"},
    ]
    for invalid in ["yes", "no", "unknown", True, False, "dmd", "dmd_nonambulatory"]:
        _assert_fail("indication_fda_labeled", indication=invalid)
    for fact, value in _base().items():
        if value is True:
            assert fields[fact]["options"] == [
                {"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"},
            ]


def test_pass_and_age_boundary():
    for age in [4.0, 5.0]:
        result = evaluate(load_pack(), _base(age_years=age))
        assert result.decision == "pass", result
        assert not result.missing_facts
    for age in [0.0, 3.9, 5.1, 6.0]:
        _assert_fail("age_fda_labeled", age_years=age)


def test_fail_non_neuromuscular():
    for specialty in ["neurologist", "primary_care", "other"]:
        _assert_fail("prescriber_specialty", prescriber_specialty=specialty)


def test_exon_monitoring_and_antibody_titer():
    for value in ["not_applicable_no_exons_1_17_or_59_71", "applicable_monitoring_mitigation_in_place"]:
        assert evaluate(load_pack(), _base(exon_high_risk_myositis_monitoring=value)).decision == "pass"
    _assert_fail("exon_high_risk_myositis_monitoring", exon_high_risk_myositis_monitoring="applicable_no_monitoring")
    _assert_fail("anti_aavrh74_titer", anti_aavrh74_titer="gte_1_400")


def test_fail_each_approval_and_denial_attestation():
    for fact, value in _base().items():
        if value is True:
            _assert_fail(fact, **{fact: False})


def test_ui_coercion():
    facts = {key: field["options"][0]["value"]
             for key, field in load_pack()["fact_ui"].items()}
    facts["age_years"] = "4"
    assert evaluate(load_pack(), _coerce_patient(facts)).decision == "pass"
    for fact, value in _base().items():
        if value is True:
            assert evaluate(load_pack(), _coerce_patient(dict(facts, **{fact: "no"}))).decision == "fail"
    assert evaluate(load_pack(), _coerce_patient(dict(facts, age_years="0"))).decision == "fail"


def test_every_ui_option():
    pack = load_pack()
    facts = {key: field["options"][0]["value"] for key, field in pack["fact_ui"].items()}
    facts["age_years"] = "4"
    passing = {
        "age_years": {"4", "5"},
        "prescriber_specialty": {"neuromuscular_specialist"},
        "exon_high_risk_myositis_monitoring": {
            "not_applicable_no_exons_1_17_or_59_71", "applicable_monitoring_mitigation_in_place"},
        "anti_aavrh74_titer": {"lt_1_400"},
        "indication": {"dmd_ambulatory_age_4_to_5"},
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
    assert catalog["elevidys"] == pack
    assert get_rule_pack("elevidys") == ("elevidys", pack)
    assert (base / "rule_packs/elevidys.json").read_bytes() == (base / "elevidys.json").read_bytes()
    assert catalog == {
        path.stem: json.loads(path.read_text())
        for path in (base / "rule_packs").glob("*.json")
    }
    with gzip.open(base / "rule_packs_all.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 104
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 94
    assert pack["alternatives"] == []
    status = json.loads((base / "ENCODING_STATUS.json").read_text())
    assert status["encoding_partial"] == 104
    assert status["encoding_text_only"] == 94
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
    print("elevidys tests ok")
