import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import check, evaluate  # noqa: E402


def load(name: str):
    return json.loads((ROOT / "data/alaska/parsed" / name).read_text())


def test_dupixent_xolair_real_packs():
    dup = load("dupixent.json")
    xol = load("xolair.json")
    catalog = {"dupixent": dup, "xolair": xol}

    # Adult asthma + specialty + step attestations → pass on encoded clauses
    ok = check(
        dup,
        {
            "age_years": 30,
            "indication": "asthma",
            "prescriber_specialty": "pulmonologist",
            "asthma_phenotype": "eosinophilic_ge_150",
            "asthma_ics_laba_3mo": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert ok.decision == "pass", ok

    # Age 10 asthma fails Dupixent asthma gate (>=6 is ok actually) — use age 4
    fail = check(
        dup,
        {
            "age_years": 4,
            "indication": "asthma",
            "prescriber_specialty": "pulmonologist",
            "asthma_phenotype": "eosinophilic_ge_150",
            "asthma_ics_laba_3mo": True,
            "not_acute_bronchospasm": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail.decision == "fail"
    # Xolair asthma allows >=6, so age 4 also fails Xolair — no alt pass
    # Use age 10: fails nothing on Dupixent asthma (>=6)... so use AD with infant age
    # Better: age 10 asthma passes Dupixent; use CRSwNP age 10 (needs >=12)
    fail2 = check(
        dup,
        {
            "age_years": 10,
            "indication": "crswnp",
            "prescriber_specialty": "allergist",
            "crswnp_failed_two_nasal_steroids_3mo": True,
            "crswnp_add_on_maintenance": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail2.decision == "fail"
    # Xolair CRSwNP needs >=18, so still no alt. Use asthma age that fails Dupixent AD path...
    # Age 10 + indication atopic_dermatitis: Dupixent AD allows 0.5y so passes.
    # Fail Dupixent with age 3 asthma (Dupixent asthma needs 6) — Xolair asthma needs 6 too.
    # Fail Dupixent with bullous_pemphigoid age 10 (needs 18) — Xolair won't have that indication.
    fail3 = check(
        dup,
        {
            "age_years": 10,
            "indication": "bullous_pemphigoid",
            "prescriber_specialty": "dermatologist",
            "bp_confirmed_serology_or_biopsy": True,
            "bp_bpdai_and_nrs_thresholds": True,
            "bp_failed_two_standard_therapies": True,
            "bp_initial_ocs_combination": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail3.decision == "fail"
    # Xolair won't pass (indication not in list) → alternatives empty is OK
    assert isinstance(fail3.alternatives, list)

    # Cross-alt: Dupixent COPD age 10 fails; not useful. 
    # Dupixent asthma age 5 fails (>=6); Xolair asthma also >=6 — both fail.
    # Dupixent CRS age 10 fails (>=12); Xolair asthma with same patient facts won't match indication.
    # To get an alt pass: patient qualifies for Xolair asthma but not Dupixent CRS:
    fail_alt = check(
        dup,
        {
            "age_years": 10,
            "indication": "crswnp",
            "prescriber_specialty": "allergist",
            "crswnp_failed_two_nasal_steroids_3mo": True,
            "crswnp_add_on_maintenance": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail_alt.decision == "fail"
    # Point alternatives at xolair but indication is crswnp — xolair needs 18 for that.
    # Change catalog alternative evaluation: use asthma patient who fails Dupixent age on COPD
    fail_copd = check(
        dup,
        {
            "age_years": 10,
            "indication": "copd",
            "prescriber_specialty": "pulmonologist",
            "copd_failed_triple_therapy_3mo": True,
            "copd_exacerbation_history_met": True,
            "copd_spirometry_criteria_met": True,
            "copd_eos_ge_300_60d": True,
            "not_used_with_another_biologic": True,
        },
        catalog,
    )
    assert fail_copd.decision == "fail"

    need = check(dup, {"indication": "asthma"}, catalog)
    assert need.decision == "need_info"
    assert "age_years" in need.missing_facts


def test_text_only_never_autopass():
    packs_dir = ROOT / "data/alaska/parsed/rule_packs"
    text_packs = []
    for p in packs_dir.glob("*.json"):
        data = json.loads(p.read_text())
        if data.get("encoding_status") == "text_only":
            text_packs.append(data)
            if len(text_packs) >= 3:
                break
    assert text_packs, "expected text_only rule packs from ingest"
    for pack in text_packs:
        # Even with invented facts, must not pass
        result = evaluate(
            pack,
            {
                "age_years": 40,
                "indication": "asthma",
                "prescriber_specialty": "pulmonologist",
                "prior_therapy_failures": ["x"],
                "lab_ige_or_eosinophil": 100,
            },
        )
        assert result.decision == "need_info"
        assert any("encoding_incomplete" in n for n in result.notes)


def test_xolair_pass():
    xol = load("xolair.json")
    ok = check(
        xol,
        {
            "age_years": 30,
            "indication": "asthma",
            "prescriber_specialty": "allergist",
        },
    )
    assert ok.decision == "pass"


if __name__ == "__main__":
    test_dupixent_xolair_real_packs()
    test_text_only_never_autopass()
    test_xolair_pass()
    print("ok")
