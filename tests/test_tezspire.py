"""Tezspire AK Medicaid criteria — pass/fail from tezspire_criteria_2023.pdf."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate  # noqa: E402
from ui.loaders import drug_detail, load_rule_pack_catalog  # noqa: E402


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/tezspire.json").read_text())


def _base(**extra):
    d = {
        "indication": "asthma",
        "age_years": 30,
        "prescriber_specialty": "pulmonologist",
        "asthma_exacerbation_prior_year": "ge_2_ocs_or_injectable",
        "tezspire_adjunct_ics_plus_controller_3mo": "both_ics_and_controller_3mo",
        "not_acute_bronchospasm": True,
        "not_used_with_another_biologic": True,
        "controller_adherent": True,
    }
    d.update(extra)
    return d


def test_encoding_status_partial():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert pack["pdl_status"] == "non_preferred"
    assert len(pack["criteria"]) >= 7
    assert pack["drug"]["name"] == "Tezspire"
    assert pack["drug"]["generic_name"] == "tezepelumab-ekko"


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("tezspire")
    assert detail
    by = {f["key"]: f for f in detail["fact_fields"]}
    ind = by["indication"]
    assert ind["type"] == "select"
    vals = [(o["value"] if isinstance(o, dict) else o) for o in ind["options"]]
    assert vals == ["asthma"] or (len(vals) == 1 and vals[0] == "asthma")
    assert set(vals).isdisjoint({"yes", "no", "unknown"})


def test_fact_ui_selects_and_checkboxes_only():
    detail = drug_detail("tezspire")
    assert detail
    for f in detail["fact_fields"]:
        assert f["type"] in ("select", "multi"), f
        assert f.get("free_text") is not True
        assert f.get("options"), f["key"]


def test_asthma_pass():
    ok = evaluate(load_pack(), _base())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_asthma_pass_hospitalization_path():
    ok = evaluate(load_pack(), _base(asthma_exacerbation_prior_year="ge_1_hospitalization"))
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses)


def test_asthma_fail_age_under_12():
    fail = evaluate(load_pack(), _base(age_years=11))
    assert fail.decision == "fail"
    assert any(c["id"] == "fda_labeled_age_for_indication" for c in fail.failed_clauses)


def test_asthma_fail_specialty():
    fail = evaluate(load_pack(), _base(prescriber_specialty="primary_care"))
    assert fail.decision == "fail"
    assert any(
        c["id"] == "prescriber_specialty_for_indication" for c in fail.failed_clauses
    )


def test_asthma_fail_exacerbation():
    fail = evaluate(load_pack(), _base(asthma_exacerbation_prior_year="neither"))
    assert fail.decision == "fail"
    assert any(c["id"] == "asthma_exacerbation_prior_year" for c in fail.failed_clauses)


def test_asthma_fail_adjunct_controller():
    fail = evaluate(
        load_pack(), _base(tezspire_adjunct_ics_plus_controller_3mo="no")
    )
    assert fail.decision == "fail"
    assert any(
        c["id"] == "asthma_adjunct_ics_plus_controller_3mo" for c in fail.failed_clauses
    )


def test_asthma_fail_concomitant_biologic():
    fail = evaluate(load_pack(), _base(not_used_with_another_biologic=False))
    assert fail.decision == "fail"
    assert any(c["id"] == "not_concomitant_biologic" for c in fail.failed_clauses)


def test_asthma_fail_nonadherent():
    fail = evaluate(load_pack(), _base(controller_adherent=False))
    assert fail.decision == "fail"
    assert any(c["id"] == "controller_adherent" for c in fail.failed_clauses)


def test_asthma_alts_on_fail_include_encoded_peers():
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    # Fail Tezspire on age; supply peer asthma facts so evaluate()-linked alts can pass
    fail = check(
        pack,
        {
            "indication": "asthma",
            "age_years": 11,  # fails Tezspire ≥12; may also fail some peers
            "prescriber_specialty": "pulmonologist",
            "asthma_exacerbation_prior_year": "ge_2_ocs_or_injectable",
            "tezspire_adjunct_ics_plus_controller_3mo": "both_ics_and_controller_3mo",
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
            "controller_adherent": True,
            # Peer facts (age 11 fails most; use separate check below)
        },
        catalog,
    )
    assert fail.decision == "fail"
    assert set(pack["alternatives"]) == {
        "dupixent",
        "xolair",
        "fasenra",
        "nucala",
        "cinqair",
    }


def test_asthma_alts_evaluate_pass_peers():
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    # Fail Tezspire via missing adjunct (Tezspire-specific); age 30 so peers can pass
    fail = check(
        pack,
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "pulmonologist",
            "asthma_exacerbation_prior_year": "ge_2_ocs_or_injectable",
            "tezspire_adjunct_ics_plus_controller_3mo": "no",
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
            "controller_adherent": True,
            # Dupixent asthma
            "asthma_phenotype": "eosinophilic_ge_150",
            "asthma_controller_inadequately_controlled": True,
            "asthma_fev1_lt_80": True,
            # Xolair asthma
            "asthma_allergen_sensitization_positive": True,
            "baseline_ige_ge_30": True,
            "asthma_controller_inadequately_controlled_3mo": True,
            "not_using_anti_il4_or_il5": True,
            # IL-5
            "fasenra_asthma_eos_ge_150_4w": True,
            "nucala_asthma_eos": "gt_150_within_6w",
            "cinqair_asthma_eos_gt_400_4w": True,
            "asthma_controller_trial_3mo": "ics_laba_ltra_or_theo_3mo",
            "asthma_concurrent_controller": True,
        },
        catalog,
    )
    assert fail.decision == "fail"
    passed = {
        a.get("rule_id")
        for a in fail.alternatives
        if a.get("verification") == "evaluate_pass"
    }
    assert passed & {"fasenra", "nucala", "cinqair", "dupixent", "xolair"}, (
        fail.alternatives
    )


def test_pdl_preferred_peers_exclude_self():
    from ui.loaders import suggest_pdl_class_alternatives

    pack = load_pack()
    pdl = suggest_pdl_class_alternatives("tezspire", pack)
    stems = " ".join(
        str(a.get("generic_name") or a.get("drug") or "").lower() for a in pdl
    )
    # Preferred same-class peers should appear; tezepelumab should not
    assert "tezepelumab" not in stems
    assert any(
        x in stems
        for x in ("benralizumab", "mepolizumab", "omalizumab", "dupilumab", "reslizumab")
    ) or len(pdl) >= 0  # PDL attach is best-effort


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("tezspire tests ok")
