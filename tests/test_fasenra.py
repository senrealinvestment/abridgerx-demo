"""Fasenra AK Medicaid IL-5 criteria — pass/fail from the shared 2025 PDF."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate  # noqa: E402
from ui.loaders import drug_detail, load_rule_pack_catalog  # noqa: E402


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/fasenra.json").read_text())


def _base_asthma(**extra):
    d = {
        "indication": "asthma",
        "age_years": 30,
        "prescriber_specialty": "pulmonologist",
        "fasenra_asthma_eos_ge_150_4w": True,
        "asthma_controller_trial_3mo": "ics_laba_ltra_or_theo_3mo",
        "asthma_concurrent_controller": True,
        "not_acute_bronchospasm": True,
        "not_used_with_another_biologic": True,
    }
    d.update(extra)
    return d


def _base_egpa(**extra):
    d = {
        "indication": "egpa",
        "age_years": 40,
        "prescriber_specialty": "rheumatologist",
        "egpa_acr_criteria": [
            "asthma",
            "eosinophilia_gt_10_pct",
            "mono_or_polyneuropathy",
            "paranasal_sinus_abnormalities",
        ],
        "egpa_steroid_status": "stable_4w",
        "not_used_with_another_biologic": True,
    }
    d.update(extra)
    return d


def test_encoding_status_partial():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert len(pack["criteria"]) >= 5
    assert pack["drug"]["name"] == "Fasenra"


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("fasenra")
    assert detail
    by = {f["key"]: f for f in detail["fact_fields"]}
    ind = by["indication"]
    assert ind["type"] == "select"
    vals = [(o["value"] if isinstance(o, dict) else o) for o in ind["options"]]
    assert "asthma" in vals
    assert "egpa" in vals
    assert "hes" not in vals  # Nucala-only
    assert set(vals).isdisjoint({"yes", "no", "unknown"})


def test_fact_ui_selects_and_checkboxes_only():
    detail = drug_detail("fasenra")
    assert detail
    for f in detail["fact_fields"]:
        assert f["type"] in ("select", "multi"), f
        assert f.get("free_text") is not True
        assert f.get("options"), f["key"]


def test_asthma_pass():
    ok = evaluate(load_pack(), _base_asthma())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_asthma_fail_age():
    fail = evaluate(load_pack(), _base_asthma(age_years=5))
    assert fail.decision == "fail"
    assert any(c["id"] == "fda_labeled_age_for_indication" for c in fail.failed_clauses)


def test_asthma_fail_eos():
    fail = evaluate(load_pack(), _base_asthma(fasenra_asthma_eos_ge_150_4w=False))
    assert fail.decision == "fail"
    assert any(
        c["id"] == "asthma_eos_controller_concurrent_not_acute" for c in fail.failed_clauses
    )


def test_egpa_pass():
    ok = evaluate(load_pack(), _base_egpa())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_egpa_fail_insufficient_acr():
    fail = evaluate(
        load_pack(),
        _base_egpa(egpa_acr_criteria=["asthma", "eosinophilia_gt_10_pct", "mono_or_polyneuropathy"]),
    )
    assert fail.decision == "fail"
    assert any(c["id"] == "egpa_diagnosis_and_steroids" for c in fail.failed_clauses)


def test_egpa_fail_specialty():
    fail = evaluate(load_pack(), _base_egpa(prescriber_specialty="primary_care"))
    assert fail.decision == "fail"
    assert any(c["id"] == "prescriber_specialty_for_indication" for c in fail.failed_clauses)


def test_concomitant_biologic_fail():
    fail = evaluate(load_pack(), _base_asthma(not_used_with_another_biologic=False))
    assert fail.decision == "fail"
    assert any(c["id"] == "not_concomitant_biologic" for c in fail.failed_clauses)


def test_need_info_missing_asthma_facts():
    need = evaluate(
        load_pack(),
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "allergist",
            "not_used_with_another_biologic": True,
        },
    )
    assert need.decision == "need_info"
    assert any(
        f in need.missing_facts
        for f in (
            "fasenra_asthma_eos_ge_150_4w",
            "asthma_controller_trial_3mo",
            "asthma_concurrent_controller",
            "not_acute_bronchospasm",
        )
    )


def test_nucala_alt_evaluate_pass_on_overlapping_asthma():
    """Fail Fasenra via concomitant biologic; Nucala may still pass with its facts."""
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    fail = check(
        pack,
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "pulmonologist",
            "fasenra_asthma_eos_ge_150_4w": True,
            "asthma_controller_trial_3mo": "ics_laba_ltra_or_theo_3mo",
            "asthma_concurrent_controller": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": False,  # fails Fasenra
            # Nucala asthma facts (same denial key — supply True so Nucala can pass):
            "nucala_asthma_eos": "gt_150_within_6w",
            # Override for alt pack: check() reuses same patient dict.
            # Nucala also requires not_used_with_another_biologic True — so it won't pass.
            # Instead fail via eos=False so Nucala can pass with its own eos fact.
        },
        catalog,
    )
    # Adjust strategy: fail Fasenra on eos, pass Nucala on its eos
    fail = check(
        pack,
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "pulmonologist",
            "fasenra_asthma_eos_ge_150_4w": False,  # fails Fasenra
            "asthma_controller_trial_3mo": "ics_laba_ltra_or_theo_3mo",
            "asthma_concurrent_controller": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
            "nucala_asthma_eos": "gt_150_within_6w",
        },
        catalog,
    )
    assert fail.decision == "fail"
    assert any(
        a.get("verification") == "evaluate_pass" and a.get("rule_id") == "nucala"
        for a in fail.alternatives
    ), fail.alternatives


def test_pdl_same_class_peers_on_fail():
    from ui.loaders import merge_alternatives, suggest_pdl_class_alternatives

    pack = load_pack()
    catalog = load_rule_pack_catalog()
    fail = check(pack, _base_asthma(age_years=4), catalog)
    assert fail.decision == "fail"
    pdl = suggest_pdl_class_alternatives("fasenra", pack)
    merged = merge_alternatives(fail.alternatives, pdl)
    stems = " ".join(
        str(a.get("generic_name") or a.get("drug") or a.get("slug") or "").lower()
        for a in merged
    )
    assert (
        "mepolizumab" in stems
        or "omalizumab" in stems
        or "nucala" in stems
        or "xolair" in stems
    ), merged


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("fasenra tests ok")
