"""Atypical antipsychotic therapeutic duplication partial encoding."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / "data/alaska/parsed"
SLUG = "atypical-antipsychotic-therapeutic-duplication"


def pack():
    return json.loads((BASE / f"rule_packs/{SLUG}.json").read_text())


def dual(**updates):
    return dict({
        "pa_trigger": "therapeutic_duplication_gt1_atypical",
        "condition_and_medical_necessity_documented": True,
        "cannot_discontinue_initial_atypical": True,
        "treatment_plan_monitoring": True,
        "single_drug_ge_2_weeks_adequate_dose": True,
    }, **updates)


def pediatric(**updates):
    return dict({
        "pa_trigger": "atypical_in_child_under_5",
        "condition_and_medical_necessity_documented": True,
        "treatment_plan_monitoring": True,
    }, **updates)


def test_dual_and_pediatric_paths():
    assert evaluate(pack(), dual()).decision == "pass"
    assert evaluate(pack(), pediatric()).decision == "pass"
    assert evaluate(pack(), dual(cannot_discontinue_initial_atypical=False)).decision == "fail"
    assert evaluate(pack(), dual(single_drug_ge_2_weeks_adequate_dose=False)).decision == "fail"
    # pediatric path does not require dual-only gates
    assert evaluate(pack(), pediatric()).decision == "pass"
    for trigger in ["yes", "no", "unknown", True, False, "other"]:
        assert evaluate(pack(), dual(pa_trigger=trigger)).decision == "fail"


def test_missing_facts_dual():
    for key in dual():
        patient = dual()
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == "need_info"
        assert key in result.missing_facts


def test_ui_catalog():
    detail = drug_detail(SLUG)
    assert detail["can_evaluate"]
    p = pack()
    assert p["encoding_status"] == "partial" and p["source"]["effective_date"] == "2012-03-16"
    assert (BASE / f"{SLUG}.json").read_bytes() == (BASE / f"rule_packs/{SLUG}.json").read_bytes()
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(x["encoding_status"] == "partial" for x in catalog.values()) == 198
    assert sum(x["encoding_status"] == "text_only" for x in catalog.values()) == 0
    status = json.loads((BASE / "ENCODING_STATUS.json").read_text())
    assert (status["encoding_partial"], status["encoding_text_only"]) == (198, 0)
    with gzip.open(BASE / "rule_packs_all.json.gz", "rt") as stream:
        assert json.load(stream) == catalog
    # coerce yes/no
    patient = dual(condition_and_medical_necessity_documented="yes",
                   cannot_discontinue_initial_atypical="yes",
                   treatment_plan_monitoring="yes",
                   single_drug_ge_2_weeks_adequate_dose="yes")
    assert evaluate(pack(), _coerce_patient(patient)).decision == "pass"
