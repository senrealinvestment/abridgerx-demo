"""Dupixent AK Medicaid criteria — pass/fail cases from the 2025 criteria PDF."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate  # noqa: E402
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog  # noqa: E402


def load_dup():
    return json.loads((ROOT / "data/alaska/parsed/dupixent.json").read_text())


def _base_ad(**extra):
    d = {
        "indication": "atopic_dermatitis",
        "age_years": 18,
        "prescriber_specialty": "dermatologist",
        "ad_bsa_severity_documented": True,
        "ad_topical_failures": [
            "medium_high_tcs_adult_or_low_tcs_pediatric",
            "topical_calcineurin_inhibitor",
        ],
        "not_used_with_another_biologic": True,
    }
    d.update(extra)
    return d


def _base_asthma(**extra):
    d = {
        "indication": "asthma",
        "age_years": 30,
        "prescriber_specialty": "pulmonologist",
        "asthma_phenotype": "eosinophilic_ge_150",
        "asthma_ics_laba_3mo": True,
        "not_acute_bronchospasm": True,
        "not_used_with_another_biologic": True,
    }
    d.update(extra)
    return d


def test_encoding_status_partial():
    pack = load_dup()
    assert pack["encoding_status"] == "partial"
    assert len(pack["criteria"]) >= 10


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("dupixent")
    assert detail
    by = {f["key"]: f for f in detail["fact_fields"]}
    ind = by["indication"]
    assert ind["type"] == "select"
    assert ind["option_source"] in ("fact_ui", "predicates")
    vals = [
        (o["value"] if isinstance(o, dict) else o) for o in ind["options"]
    ]
    assert "atopic_dermatitis" in vals
    assert "asthma" in vals
    assert "bullous_pemphigoid" in vals
    assert "yes" not in vals
    assert "no" not in vals
    assert "unknown" not in vals
    # No fact field should use Yes/No/Unknown as indication
    for f in detail["fact_fields"]:
        if f["key"] == "indication":
            opt_vals = [
                (o["value"] if isinstance(o, dict) else o) for o in f["options"]
            ]
            assert set(opt_vals).isdisjoint({"yes", "no", "unknown"})


def test_fact_ui_selects_and_checkboxes_only():
    detail = drug_detail("dupixent")
    assert detail
    for f in detail["fact_fields"]:
        assert f["type"] in ("select", "multi"), f
        assert f.get("free_text") is not True
        assert f.get("options"), f["key"]
    by = {f["key"]: f for f in detail["fact_fields"]}
    assert by["ad_topical_failures"]["type"] == "multi"
    assert by["asthma_phenotype"]["type"] == "select"


def test_ad_pass():
    pack = load_dup()
    ok = evaluate(pack, _base_ad())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_ad_fail_age_infant_ok_but_specialty_wrong():
    pack = load_dup()
    # Age 0.5 OK for AD; primary_care fails specialty
    fail = evaluate(
        pack,
        _base_ad(age_years=0.5, prescriber_specialty="primary_care"),
    )
    assert fail.decision == "fail"
    assert any(c["id"] == "prescriber_specialty_for_indication" for c in fail.failed_clauses)


def test_ad_fail_insufficient_topicals():
    pack = load_dup()
    fail = evaluate(
        pack,
        _base_ad(ad_topical_failures=["topical_calcineurin_inhibitor"]),
    )
    assert fail.decision == "fail"
    assert any(c["id"] == "ad_documentation_and_step_therapy" for c in fail.failed_clauses)


def test_asthma_pass():
    pack = load_dup()
    ok = evaluate(pack, _base_asthma())
    assert ok.decision == "pass", ok


def test_asthma_fail_age_under_6():
    pack = load_dup()
    fail = evaluate(pack, _base_asthma(age_years=4))
    assert fail.decision == "fail"
    assert any(c["id"] == "fda_labeled_age_for_indication" for c in fail.failed_clauses)


def test_asthma_fail_wrong_specialty_dermatologist():
    pack = load_dup()
    fail = evaluate(pack, _base_asthma(prescriber_specialty="dermatologist"))
    assert fail.decision == "fail"
    assert any(c["id"] == "prescriber_specialty_for_indication" for c in fail.failed_clauses)


def test_asthma_fail_neither_phenotype():
    pack = load_dup()
    fail = evaluate(pack, _base_asthma(asthma_phenotype="neither"))
    assert fail.decision == "fail"
    assert any(
        c["id"] == "asthma_phenotype_controller_and_not_acute" for c in fail.failed_clauses
    )


def test_asthma_fail_acute_use():
    pack = load_dup()
    fail = evaluate(pack, _base_asthma(not_acute_bronchospasm=False))
    assert fail.decision == "fail"


def test_crswnp_age_fail_and_pass():
    pack = load_dup()
    base = {
        "indication": "crswnp",
        "prescriber_specialty": "ent",
        "crswnp_failed_two_nasal_steroids_3mo": True,
        "crswnp_add_on_maintenance": True,
        "not_used_with_another_biologic": True,
    }
    fail = evaluate(pack, {**base, "age_years": 10})
    assert fail.decision == "fail"
    ok = evaluate(pack, {**base, "age_years": 14})
    assert ok.decision == "pass", ok


def test_eoe_weight_gate():
    pack = load_dup()
    base = {
        "indication": "eosinophilic_esophagitis",
        "age_years": 5,
        "prescriber_specialty": "allergist",
        "eoe_eos_hpf_ge_15": True,
        "eoe_dysphagia_symptoms": True,
        "not_used_with_another_biologic": True,
    }
    fail = evaluate(pack, {**base, "weight_ge_15_kg": False})
    assert fail.decision == "fail"
    ok = evaluate(pack, {**base, "weight_ge_15_kg": True})
    assert ok.decision == "pass", ok


def test_copd_requires_pulmonologist_and_gates():
    pack = load_dup()
    base = {
        "indication": "copd",
        "age_years": 55,
        "prescriber_specialty": "pulmonologist",
        "copd_failed_triple_therapy_3mo": True,
        "copd_exacerbation_history_met": True,
        "copd_spirometry_criteria_met": True,
        "copd_eos_ge_300_60d": True,
        "not_used_with_another_biologic": True,
    }
    ok = evaluate(pack, base)
    assert ok.decision == "pass", ok
    fail_spec = evaluate(pack, {**base, "prescriber_specialty": "allergist"})
    assert fail_spec.decision == "fail"
    fail_eos = evaluate(pack, {**base, "copd_eos_ge_300_60d": False})
    assert fail_eos.decision == "fail"


def test_csu_and_bp_pass_fail():
    pack = load_dup()
    csu = {
        "indication": "chronic_spontaneous_urticaria",
        "age_years": 16,
        "prescriber_specialty": "allergist",
        "csu_duration_and_frequency_met": True,
        "csu_failed_max_antihistamine_60d": True,
        "not_used_with_another_biologic": True,
    }
    assert evaluate(pack, csu).decision == "pass"
    assert evaluate(pack, {**csu, "age_years": 10}).decision == "fail"

    bp = {
        "indication": "bullous_pemphigoid",
        "age_years": 60,
        "prescriber_specialty": "dermatologist",
        "bp_confirmed_serology_or_biopsy": True,
        "bp_bpdai_and_nrs_thresholds": True,
        "bp_failed_two_standard_therapies": True,
        "bp_initial_ocs_combination": True,
        "not_used_with_another_biologic": True,
    }
    assert evaluate(pack, bp).decision == "pass"
    assert evaluate(pack, {**bp, "bp_initial_ocs_combination": False}).decision == "fail"


def test_concomitant_biologic_denial():
    pack = load_dup()
    fail = evaluate(pack, _base_asthma(not_used_with_another_biologic=False))
    assert fail.decision == "fail"
    assert any(c["id"] == "not_concomitant_biologic" for c in fail.failed_clauses)


def test_need_info_when_step_facts_missing_for_indication():
    pack = load_dup()
    need = evaluate(
        pack,
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "pulmonologist",
            "not_used_with_another_biologic": True,
        },
    )
    assert need.decision == "need_info"
    assert "asthma_phenotype" in need.missing_facts or "asthma_ics_laba_3mo" in need.missing_facts


def test_indication_irrelevant_facts_do_not_block():
    """AD topical facts must not be required when indication is asthma."""
    pack = load_dup()
    ok = evaluate(pack, _base_asthma())
    assert ok.decision == "pass"
    assert not ok.missing_facts


def test_alternatives_on_fail_include_xolair_or_honest_label():
    pack = load_dup()
    catalog = load_rule_pack_catalog()
    # Fail Dupixent COPD age gate; Xolair won't pass COPD indication either
    fail = check(
        pack,
        {
            "indication": "copd",
            "age_years": 10,
            "prescriber_specialty": "pulmonologist",
            "copd_failed_triple_therapy_3mo": True,
            "copd_exacerbation_history_met": True,
            "copd_spirometry_criteria_met": True,
            "copd_eos_ge_300_60d": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail.decision == "fail"
    assert isinstance(fail.alternatives, list)


def test_xolair_alt_evaluate_pass_when_facts_overlap():
    """Fail Dupixent asthma via phenotype; Xolair asthma can still pass with its own gates."""
    pack = load_dup()
    catalog = load_rule_pack_catalog()
    # Dupixent fails on asthma_phenotype=neither; Xolair uses allergen/IgE/controller instead.
    fail = check(
        pack,
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "allergist",
            "asthma_phenotype": "neither",  # fails Dupixent
            "asthma_ics_laba_3mo": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
            # Xolair asthma facts (still collected on the same patient payload):
            "asthma_allergen_sensitization_positive": True,
            "baseline_ige_ge_30": True,
            "asthma_controller_inadequately_controlled_3mo": True,
            "not_using_anti_il4_or_il5": True,
        },
        catalog,
    )
    assert fail.decision == "fail"
    assert any(
        a.get("verification") == "evaluate_pass" and a.get("rule_id") == "xolair"
        for a in fail.alternatives
    ), fail.alternatives


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("dupixent tests ok")
