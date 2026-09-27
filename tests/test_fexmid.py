"""Fexmid OCR-recovered partial encoding."""
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
STEP = "ir_cyclobenzaprine_5_or_10mg_ge_5_days_suboptimal"
IND = "acute_painful_musculoskeletal_muscle_spasm"


def pack():
    return json.loads((BASE / "rule_packs/fexmid.json").read_text())


def facts(**updates):
    return dict({
        "pa_override_population": "standard_outpatient_path",
        "indication": IND,
        "age_years": 16,
        STEP: True,
        "not_on_other_muscle_relaxant": True,
    }, **updates)


def test_standard_and_override():
    assert evaluate(pack(), facts()).decision == "pass"
    assert evaluate(pack(), facts(age_years=15)).decision == "fail"
    assert evaluate(pack(), facts(age_years=40)).decision == "pass"
    assert evaluate(pack(), facts(**{STEP: False})).decision == "fail"
    assert evaluate(pack(), facts(not_on_other_muscle_relaxant=False)).decision == "fail"
    override = {"pa_override_population": "hospice_or_cancer_or_ltc", "not_on_other_muscle_relaxant": True}
    assert evaluate(pack(), override).decision == "pass"
    assert evaluate(pack(), dict(override, not_on_other_muscle_relaxant=False)).decision == "fail"


def test_ui_catalog_ocr():
    ct = json.loads((BASE / "criteria_text/fexmid.json").read_text())
    assert ct["ocr_status"] == "tesseract_recovered"
    assert "Fexmid" in ct["extracted_text"]
    detail = drug_detail("fexmid")
    assert detail["can_evaluate"]
    patient = facts(**{STEP: "yes", "not_on_other_muscle_relaxant": "yes"})
    assert evaluate(pack(), _coerce_patient(patient)).decision == "pass"
    p = pack()
    assert p["encoding_status"] == "partial" and p["source"]["effective_date"] == "2009-06-24"
    assert (BASE / "fexmid.json").read_bytes() == (BASE / "rule_packs/fexmid.json").read_bytes()
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(x["encoding_status"] == "text_only" for x in catalog.values()) == 0
    with gzip.open(BASE / "rule_packs_all.json.gz", "rt") as stream:
        assert json.load(stream) == catalog
