"""Xolair AK Medicaid criteria — pass/fail cases from the 2024 criteria PDF."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate  # noqa: E402
from ui.loaders import drug_detail, load_rule_pack_catalog  # noqa: E402


def load_xol():
    return json.loads((ROOT / "data/alaska/parsed/xolair.json").read_text())


def _base_asthma(**extra):
    d = {
        "indication": "asthma",
        "age_years": 30,
        "prescriber_specialty": "allergist",
        "not_acute_bronchospasm": True,
        "asthma_allergen_sensitization_positive": True,
        "baseline_ige_ge_30": True,
        "asthma_controller_inadequately_controlled_3mo": True,
        "not_using_anti_il4_or_il5": True,
    }
    d.update(extra)
    return d


def _base_csu(**extra):
    d = {
        "indication": "chronic_spontaneous_urticaria",
        "age_years": 18,
        "prescriber_specialty": "allergist",
        "csu_duration_and_frequency_met": True,
        "csu_failed_ltra_plus_antihistamine_2mo": True,
        "not_using_anti_il4_or_il5": True,
    }
    d.update(extra)
    return d


def _base_crswnp(**extra):
    d = {
        "indication": "crswnp",
        "age_years": 30,
        "prescriber_specialty": "pulmonologist",
        "baseline_ige_ge_30": True,
        "crswnp_failed_two_nasal_steroids_3mo": True,
        "crswnp_add_on_maintenance": True,
        "not_using_anti_il4_or_il5": True,
    }
    d.update(extra)
    return d


def _base_food(**extra):
    d = {
        "indication": "ige_mediated_food_allergy",
        "age_years": 5,
        "prescriber_specialty": "immunologist",
        "ige_food_allergy_diagnosis_confirmed": True,
        "baseline_ige_and_weight_provided": True,
        "not_using_anti_il4_or_il5": True,
    }
    d.update(extra)
    return d


def test_encoding_status_partial():
    pack = load_xol()
    assert pack["encoding_status"] == "partial"
    assert len(pack["criteria"]) >= 8
    assert pack.get("fact_ui", {}).get("indication", {}).get("type") == "select"


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("xolair")
    assert detail
    by = {f["key"]: f for f in detail["fact_fields"]}
    ind = by["indication"]
    assert ind["type"] == "select"
    assert ind["option_source"] in ("fact_ui", "predicates")
    vals = [(o["value"] if isinstance(o, dict) else o) for o in ind["options"]]
    assert "asthma" in vals
    assert "chronic_spontaneous_urticaria" in vals
    assert "crswnp" in vals
    assert "ige_mediated_food_allergy" in vals
    assert set(vals).isdisjoint({"yes", "no", "unknown"})


def test_fact_ui_selects_and_checkboxes_only():
    detail = drug_detail("xolair")
    assert detail
    for f in detail["fact_fields"]:
        assert f["type"] in ("select", "multi"), f
        assert f.get("free_text") is not True
        assert f.get("options"), f["key"]
    by = {f["key"]: f for f in detail["fact_fields"]}
    assert by["asthma_controller_inadequately_controlled_3mo"]["type"] == "select"
    assert by["not_using_anti_il4_or_il5"]["type"] == "select"


def test_asthma_pass():
    pack = load_xol()
    ok = evaluate(pack, _base_asthma())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_asthma_fail_age_under_6():
    pack = load_xol()
    fail = evaluate(pack, _base_asthma(age_years=4))
    assert fail.decision == "fail"
    assert any(c["id"] == "fda_labeled_age_for_indication" for c in fail.failed_clauses)


def test_asthma_fail_acute_use():
    pack = load_xol()
    fail = evaluate(pack, _base_asthma(not_acute_bronchospasm=False))
    assert fail.decision == "fail"
    assert any(
        c["id"] == "asthma_sensitization_ige_controller_not_acute"
        for c in fail.failed_clauses
    )


def test_asthma_fail_no_sensitization():
    pack = load_xol()
    fail = evaluate(pack, _base_asthma(asthma_allergen_sensitization_positive=False))
    assert fail.decision == "fail"


def test_asthma_fail_wrong_specialty_primary_care():
    pack = load_xol()
    fail = evaluate(pack, _base_asthma(prescriber_specialty="primary_care"))
    assert fail.decision == "fail"
    assert any(
        c["id"] == "prescriber_specialty_for_indication" for c in fail.failed_clauses
    )


def test_csu_pass_and_age_fail():
    pack = load_xol()
    assert evaluate(pack, _base_csu()).decision == "pass"
    fail = evaluate(pack, _base_csu(age_years=6))
    assert fail.decision == "fail"
    assert any(c["id"] == "fda_labeled_age_for_indication" for c in fail.failed_clauses)


def test_csu_fail_step_therapy():
    pack = load_xol()
    fail = evaluate(pack, _base_csu(csu_failed_ltra_plus_antihistamine_2mo=False))
    assert fail.decision == "fail"
    assert any(c["id"] == "csu_duration_and_step_therapy" for c in fail.failed_clauses)


def test_crswnp_pass_and_age_fail():
    pack = load_xol()
    assert evaluate(pack, _base_crswnp()).decision == "pass"
    fail = evaluate(pack, _base_crswnp(age_years=16))
    assert fail.decision == "fail"


def test_crswnp_fail_ige_and_nasal_steroids():
    pack = load_xol()
    fail_ige = evaluate(pack, _base_crswnp(baseline_ige_ge_30=False))
    assert fail_ige.decision == "fail"
    fail_step = evaluate(pack, _base_crswnp(crswnp_failed_two_nasal_steroids_3mo=False))
    assert fail_step.decision == "fail"


def test_food_allergy_pass():
    pack = load_xol()
    ok = evaluate(pack, _base_food())
    assert ok.decision == "pass", ok


def test_food_allergy_pulmonologist_not_allowed():
    pack = load_xol()
    fail = evaluate(pack, _base_food(prescriber_specialty="pulmonologist"))
    assert fail.decision == "fail"
    assert any(
        c["id"] == "prescriber_specialty_for_indication" for c in fail.failed_clauses
    )


def test_food_allergy_age_under_1():
    pack = load_xol()
    fail = evaluate(pack, _base_food(age_years=0.5))
    assert fail.decision == "fail"


def test_anti_il4_il5_denial():
    pack = load_xol()
    fail = evaluate(pack, _base_asthma(not_using_anti_il4_or_il5=False))
    assert fail.decision == "fail"
    assert any(
        c["id"] == "not_concomitant_anti_il4_or_il5" for c in fail.failed_clauses
    )


def test_need_info_when_asthma_facts_missing():
    pack = load_xol()
    need = evaluate(
        pack,
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "allergist",
            "not_using_anti_il4_or_il5": True,
        },
    )
    assert need.decision == "need_info"
    assert any(
        f in need.missing_facts
        for f in (
            "asthma_allergen_sensitization_positive",
            "baseline_ige_ge_30",
            "asthma_controller_inadequately_controlled_3mo",
            "not_acute_bronchospasm",
        )
    )


def test_indication_irrelevant_facts_do_not_block():
    """CSU patient must not be asked for asthma controller facts."""
    pack = load_xol()
    ok = evaluate(pack, _base_csu())
    assert ok.decision == "pass"
    assert not ok.missing_facts


def test_dupixent_alt_evaluate_pass_on_overlapping_asthma():
    """Fail Xolair via anti-IL4/5 concomitant; Dupixent asthma may still pass."""
    pack = load_xol()
    catalog = load_rule_pack_catalog()
    # Xolair denial: on anti-IL4/5. Dupixent asthma uses different denial fact
    # (not_used_with_another_biologic) — supply True so Dupixent can pass.
    fail = check(
        pack,
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "pulmonologist",
            "not_acute_bronchospasm": True,
            "asthma_allergen_sensitization_positive": True,
            "baseline_ige_ge_30": True,
            "asthma_controller_inadequately_controlled_3mo": True,
            "not_using_anti_il4_or_il5": False,  # fails Xolair
            # Dupixent asthma facts:
            "asthma_phenotype": "eosinophilic_ge_150",
            "asthma_ics_laba_3mo": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail.decision == "fail"
    assert any(
        a.get("verification") == "evaluate_pass" and a.get("rule_id") == "dupixent"
        for a in fail.alternatives
    ), fail.alternatives


def test_pdl_same_class_peers_on_fail():
    from ui.loaders import merge_alternatives, suggest_pdl_class_alternatives

    pack = load_xol()
    catalog = load_rule_pack_catalog()
    fail = check(pack, _base_asthma(age_years=4), catalog)
    assert fail.decision == "fail"
    pdl = suggest_pdl_class_alternatives("xolair", pack)
    merged = merge_alternatives(fail.alternatives, pdl)
    stems = " ".join(
        str(a.get("generic_name") or a.get("drug") or a.get("slug") or "").lower()
        for a in merged
    )
    # Fasenra (benralizumab) / Nucala (mepolizumab) preferred in same basket
    assert "benralizumab" in stems or "mepolizumab" in stems or "fasenra" in stems or "nucala" in stems, merged


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("xolair tests ok")
