"""Bactroban Cream partial encoding and catalog integrity."""
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
IND = "secondarily_infected_traumatic_skin_lesion_s_aureus_or_s_pyogenes"
ALLERGY = "unable_to_use_mupirocin_ointment_inactive_allergy"


def pack():
    return json.loads((BASE / "rule_packs/bactroban-cream.json").read_text())


def facts(**updates):
    return dict({"indication": IND, ALLERGY: True}, **updates)


def test_pass_fail_and_closed_indication():
    assert evaluate(pack(), facts()).decision == "pass"
    assert evaluate(pack(), facts(**{ALLERGY: False})).decision == "fail"
    for indication in ["yes", "no", "unknown", True, False, "impetigo", "ointment"]:
        assert evaluate(pack(), facts(indication=indication)).decision == "fail"


def test_missing_facts():
    for key in facts():
        patient = facts()
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == "need_info"
        assert result.missing_facts == [key]


def test_ui_and_coercion():
    detail = drug_detail("bactroban-cream")
    assert detail["can_evaluate"]
    fields = {f["key"]: f for f in detail["fact_fields"]}
    assert set(fields) == set(facts()) == set(pack()["fact_ui"])
    patient = facts(**{ALLERGY: "yes"})
    assert evaluate(pack(), _coerce_patient(patient)).decision == "pass"


def test_metadata_and_catalog():
    p = pack()
    assert p["encoding_status"] == "partial"
    assert p["source"]["effective_date"] == "2011-04-15"
    assert "inferred_required_facts" not in p and p["alternatives"] == []
    assert (BASE / "bactroban-cream.json").read_bytes() == (BASE / "rule_packs/bactroban-cream.json").read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / "rule_packs").glob("*.json")}
    assert json.loads((BASE / "rule_packs_all.json").read_text()) == catalog
    with gzip.open(BASE / "rule_packs_all.json.gz", "rt") as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(x["encoding_status"] == "partial" for x in catalog.values()) == 198
    assert sum(x["encoding_status"] == "text_only" for x in catalog.values()) == 0
    status = json.loads((BASE / "ENCODING_STATUS.json").read_text())
    assert (status["encoding_partial"], status["encoding_text_only"]) == (198, 0)
    assert status["next_candidate"] is None
