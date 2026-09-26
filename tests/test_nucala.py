"""Nucala AK Medicaid IL-5 criteria — pass/fail from the shared 2025 PDF."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate  # noqa: E402
from ui.loaders import drug_detail, load_rule_pack_catalog  # noqa: E402


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/nucala.json").read_text())


def _base_asthma(**extra):
    d = {
        "indication": "asthma",
        "age_years": 30,
        "prescriber_specialty": "pulmonologist",
        "nucala_asthma_eos": "gt_150_within_6w",
        "asthma_controller_trial_3mo": "ics_laba_ltra_or_theo_3mo",
        "asthma_concurrent_controller": True,
        "not_acute_bronchospasm": True,
        "not_used_with_another_biologic": True,
    }
    d.update(extra)
    return d


def _base_hes(**extra):
    d = {
        "indication": "hes",
        "age_years": 14,
        "prescriber_specialty": "immunologist",
        "hes_duration_no_secondary_cause": True,
        "hes_steroid_status": "ci_or_inappropriate",
        "not_used_with_another_biologic": True,
    }
    d.update(extra)
    return d


def _base_crswnp(**extra):
    d = {
        "indication": "crswnp",
        "age_years": 45,
        "prescriber_specialty": "ent",
        "crswnp_imaging_or_exam_confirmed": True,
        "crswnp_symptoms_ge_2_for_6mo": True,
        "crswnp_incs_3mo_and_continue": True,
        "not_used_with_another_biologic": True,
    }
    d.update(extra)
    return d


def _base_copd(**extra):
    d = {
        "indication": "copd",
        "age_years": 60,
        "prescriber_specialty": "pulmonologist",
        "copd_failed_triple_therapy_3mo": True,
        "copd_exacerbation_history_met": True,
        "copd_spirometry_criteria_met": True,
        "nucala_copd_eos": "ge_300_past_12mo",
        "not_used_with_another_biologic": True,
    }
    d.update(extra)
    return d


def test_encoding_status_partial():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert len(pack["criteria"]) >= 8


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("nucala")
    assert detail
    by = {f["key"]: f for f in detail["fact_fields"]}
    ind = by["indication"]
    vals = [(o["value"] if isinstance(o, dict) else o) for o in ind["options"]]
    for v in ("asthma", "egpa", "hes", "crswnp", "copd"):
        assert v in vals
    assert set(vals).isdisjoint({"yes", "no", "unknown"})


def test_asthma_pass():
    ok = evaluate(load_pack(), _base_asthma())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_asthma_alt_eos_300_pass():
    ok = evaluate(load_pack(), _base_asthma(nucala_asthma_eos="gt_300_past_12mo"))
    assert ok.decision == "pass"


def test_hes_pass():
    ok = evaluate(load_pack(), _base_hes())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_hes_fail_age_under_12():
    fail = evaluate(load_pack(), _base_hes(age_years=11))
    assert fail.decision == "fail"
    assert any(c["id"] == "fda_labeled_age_for_indication" for c in fail.failed_clauses)


def test_crswnp_pass():
    ok = evaluate(load_pack(), _base_crswnp())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_crswnp_fail_specialty_pulmonologist():
    fail = evaluate(load_pack(), _base_crswnp(prescriber_specialty="pulmonologist"))
    assert fail.decision == "fail"
    assert any(c["id"] == "prescriber_specialty_for_indication" for c in fail.failed_clauses)


def test_copd_pass():
    ok = evaluate(load_pack(), _base_copd())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_copd_fail_eos():
    fail = evaluate(load_pack(), _base_copd(nucala_copd_eos="neither"))
    assert fail.decision == "fail"
    assert any(
        c["id"] == "copd_triple_exacerbation_spirometry_eos" for c in fail.failed_clauses
    )


def test_indication_irrelevant_facts_do_not_block():
    """HES patient must not be asked for asthma controller facts."""
    ok = evaluate(load_pack(), _base_hes())
    assert ok.decision == "pass"
    assert not ok.missing_facts


def test_fasenra_alt_on_egpa_overlap():
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    # Fail Nucala EGPA via insufficient ACR; Fasenra EGPA with enough ACR + steroids
    fail = check(
        pack,
        {
            "indication": "egpa",
            "age_years": 40,
            "prescriber_specialty": "rheumatologist",
            "egpa_acr_criteria": ["asthma", "eosinophilia_gt_10_pct"],  # only 2 — fails Nucala
            "egpa_steroid_status": "stable_4w",
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail.decision == "fail"
    # Fasenra also needs ≥4 ACR — same facts, so won't pass. Use asthma overlap instead.
    fail = check(
        pack,
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "pulmonologist",
            "nucala_asthma_eos": "neither",  # fails Nucala
            "asthma_controller_trial_3mo": "ics_laba_ltra_or_theo_3mo",
            "asthma_concurrent_controller": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
            "fasenra_asthma_eos_ge_150_4w": True,
        },
        catalog,
    )
    assert fail.decision == "fail"
    assert any(
        a.get("verification") == "evaluate_pass" and a.get("rule_id") == "fasenra"
        for a in fail.alternatives
    ), fail.alternatives


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("nucala tests ok")
