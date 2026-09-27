"""Ergocalciferol oral drops OCR-recovered partial encoding."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / "data/alaska/parsed"


def pack():
    return json.loads((BASE / "rule_packs/ergocalciferol.json").read_text())


def test_rickets_only_and_catalog():
    assert evaluate(pack(), {"indication": "rickets"}).decision == "pass"
    for indication in ["vitamin_d_deficiency", "hypoparathyroidism", "yes", "no", True, False]:
        assert evaluate(pack(), {"indication": indication}).decision == "fail"
    assert evaluate(pack(), {}).decision == "need_info"
    ct = json.loads((BASE / "criteria_text/ergocalciferol.json").read_text())
    assert ct["ocr_status"] == "tesseract_recovered" and "Rickets" in ct["extracted_text"]
    detail = drug_detail("ergocalciferol")
    assert detail["can_evaluate"]
    assert evaluate(pack(), _coerce_patient({"indication": "rickets"})).decision == "pass"
    p = pack()
    assert p["encoding_status"] == "partial"
    assert p["source"]["effective_date"] == "2009-06-04"
    assert "vitamin-d-50" in p["alternatives"]
    assert (BASE / "ergocalciferol.json").read_bytes() == (BASE / "rule_packs/ergocalciferol.json").read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog["ergocalciferol"]["encoding_status"] == "partial"
    assert catalog["000-unit"]["encoding_status"] == "partial"
    assert catalog["vitamin-d-50"]["encoding_status"] == "partial"
    assert sum(x["encoding_status"] == "text_only" for x in catalog.values()) == 0
    status = json.loads((BASE / "ENCODING_STATUS.json").read_text())
    assert (status["encoding_partial"], status["encoding_text_only"]) == (198, 0)
