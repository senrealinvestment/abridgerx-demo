"""Indication-gated fact_ui.when + clause.when — multi-indication UX."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import evaluate, _when_applies  # noqa: E402
from ui.loaders import drug_detail, load_rule_pack_catalog  # noqa: E402


def _clear_caches():
    load_rule_pack_catalog.cache_clear()


def test_when_applies_helper():
    assert _when_applies(None, {}) is True
    assert _when_applies({"fact": "indication", "in": ["asthma"]}, {}) is False
    assert (
        _when_applies(
            {"fact": "indication", "in": ["asthma"]},
            {"indication": "asthma"},
        )
        is True
    )
    assert (
        _when_applies(
            {"fact": "indication", "in": ["asthma"]},
            {"indication": "atopic_dermatitis"},
        )
        is False
    )


def test_dupixent_fact_ui_when_on_indication_specific_fields():
    _clear_caches()
    detail = drug_detail("dupixent")
    by = {f["key"]: f for f in detail["fact_fields"]}
    assert "when" not in by["indication"]
    assert "when" not in by["age_years"]
    assert "when" not in by["prescriber_specialty"]
    assert "when" not in by["not_used_with_another_biologic"]
    assert by["asthma_phenotype"]["when"] == {
        "fact": "indication",
        "in": ["asthma"],
    }
    assert by["ad_topical_failures"]["when"]["in"] == ["atopic_dermatitis"]
    assert by["copd_eos_ge_300_60d"]["when"]["in"] == ["copd"]


def test_dupixent_evaluate_skips_other_indication_clauses():
    _clear_caches()
    pack = json.loads(
        (ROOT / "data/alaska/parsed/rule_packs/dupixent.json").read_text()
    )
    # Asthma pass payload — must not need_info on AD/COPD facts
    patient = {
        "indication": "asthma",
        "age_years": 30,
        "prescriber_specialty": "pulmonologist",
        "asthma_phenotype": "eosinophilic_ge_150",
        "asthma_ics_laba_3mo": True,
        "not_acute_bronchospasm": True,
        "not_used_with_another_biologic": True,
    }
    ok = evaluate(pack, patient)
    assert ok.decision == "pass", (ok.decision, ok.missing_facts, ok.failed_clauses)
    assert not ok.missing_facts

    # AD-only facts present without AD indication must not break asthma pass
    patient_extra = dict(patient)
    # no AD facts — still pass
    ok2 = evaluate(pack, patient_extra)
    assert ok2.decision == "pass"

    # Pick AD → asthma facts irrelevant; AD facts required
    ad_need = evaluate(
        pack,
        {
            "indication": "atopic_dermatitis",
            "age_years": 18,
            "prescriber_specialty": "dermatologist",
            "not_used_with_another_biologic": True,
        },
    )
    assert ad_need.decision == "need_info"
    assert "ad_bsa_severity_documented" in ad_need.missing_facts or (
        "ad_topical_failures" in ad_need.missing_facts
    )
    assert "asthma_phenotype" not in ad_need.missing_facts


def test_xolair_fact_ui_when():
    _clear_caches()
    detail = drug_detail("xolair")
    by = {f["key"]: f for f in detail["fact_fields"]}
    assert by["asthma_allergen_sensitization_positive"]["when"]["in"] == ["asthma"]
    assert set(by["baseline_ige_ge_30"]["when"]["in"]) == {"asthma", "crswnp"}
    assert by["ige_food_allergy_diagnosis_confirmed"]["when"]["in"] == [
        "ige_mediated_food_allergy"
    ]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
