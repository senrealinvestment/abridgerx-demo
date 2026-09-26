"""Cinqair AK Medicaid IL-5 criteria — pass/fail from the shared 2025 PDF."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate  # noqa: E402
from ui.loaders import drug_detail, load_rule_pack_catalog  # noqa: E402


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/cinqair.json").read_text())


def _base_asthma(**extra):
    d = {
        "indication": "asthma",
        "age_years": 30,
        "prescriber_specialty": "allergist",
        "cinqair_asthma_eos_gt_400_4w": True,
        "asthma_controller_trial_3mo": "ics_laba_ltra_or_theo_3mo",
        "asthma_concurrent_controller": True,
        "not_acute_bronchospasm": True,
        "not_used_with_another_biologic": True,
    }
    d.update(extra)
    return d


def test_encoding_status_partial():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert pack["pdl_status"] == "non_preferred"
    assert len(pack["criteria"]) >= 4


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("cinqair")
    assert detail
    by = {f["key"]: f for f in detail["fact_fields"]}
    ind = by["indication"]
    vals = [(o["value"] if isinstance(o, dict) else o) for o in ind["options"]]
    assert vals == ["asthma"] or (len(vals) == 1 and vals[0] == "asthma")
    assert set(vals).isdisjoint({"yes", "no", "unknown"})


def test_asthma_pass():
    ok = evaluate(load_pack(), _base_asthma())
    assert ok.decision == "pass", (ok.decision, ok.failed_clauses, ok.missing_facts)


def test_asthma_fail_age_under_18():
    fail = evaluate(load_pack(), _base_asthma(age_years=17))
    assert fail.decision == "fail"
    assert any(c["id"] == "fda_labeled_age_for_indication" for c in fail.failed_clauses)


def test_asthma_fail_eos():
    fail = evaluate(load_pack(), _base_asthma(cinqair_asthma_eos_gt_400_4w=False))
    assert fail.decision == "fail"


def test_preferred_il5_alts_on_fail():
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    fail = check(
        pack,
        {
            "indication": "asthma",
            "age_years": 30,
            "prescriber_specialty": "pulmonologist",
            "cinqair_asthma_eos_gt_400_4w": False,  # fails Cinqair
            "asthma_controller_trial_3mo": "ics_laba_ltra_or_theo_3mo",
            "asthma_concurrent_controller": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
            "fasenra_asthma_eos_ge_150_4w": True,
            "nucala_asthma_eos": "gt_150_within_6w",
        },
        catalog,
    )
    assert fail.decision == "fail"
    passed = {
        a.get("rule_id")
        for a in fail.alternatives
        if a.get("verification") == "evaluate_pass"
    }
    assert "fasenra" in passed or "nucala" in passed, fail.alternatives


def test_pdl_preferred_peers_exclude_self():
    from ui.loaders import suggest_pdl_class_alternatives

    pack = load_pack()
    pdl = suggest_pdl_class_alternatives("cinqair", pack)
    stems = " ".join(
        str(a.get("generic_name") or a.get("drug") or "").lower() for a in pdl
    )
    assert "benralizumab" in stems or "mepolizumab" in stems or "omalizumab" in stems, pdl
    assert "reslizumab" not in stems


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("cinqair tests ok")
