"""Soma OCR-recovered partial encoding."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / "data/alaska/parsed"
IND = "acute_painful_musculoskeletal_discomfort"


def pack():
    return json.loads((BASE / "rule_packs/soma.json").read_text())


def facts(**updates):
    return dict({
        "pa_override_population": "standard_outpatient_path",
        "indication": IND,
        "age_years": 16,
        "not_on_other_muscle_relaxant": True,
    }, **updates)


def test_paths_and_catalog():
    assert evaluate(pack(), facts()).decision == "pass"
    assert evaluate(pack(), facts(age_years=15)).decision == "fail"
    override = {"pa_override_population": "hospice_or_cancer_or_ltc", "not_on_other_muscle_relaxant": True}
    assert evaluate(pack(), override).decision == "pass"
    assert evaluate(pack(), dict(override, not_on_other_muscle_relaxant=False)).decision == "fail"
    ct = json.loads((BASE / "criteria_text/soma.json").read_text())
    assert ct["ocr_status"] == "tesseract_recovered" and "Soma" in ct["extracted_text"]
    detail = drug_detail("soma")
    assert detail["can_evaluate"]
    assert evaluate(pack(), _coerce_patient(facts(not_on_other_muscle_relaxant="yes"))).decision == "pass"
    catalog = load_rule_pack_catalog()
    assert catalog["soma"]["encoding_status"] == "partial"
    assert sum(x["encoding_status"] == "text_only" for x in catalog.values()) == 0
    assert (BASE / "soma.json").read_bytes() == (BASE / "rule_packs/soma.json").read_bytes()
