"""Stadol / butorphanol nasal spray OCR-recovered partial encoding."""
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
    return json.loads((BASE / "rule_packs/stadol.json").read_text())


def pain(**updates):
    return dict({
        "pa_override_population": "standard_outpatient_path",
        "age_years": 18,
        "first_line_medication_suboptimal": True,
        "indication": "pain_opioid_analgesic_appropriate",
        "cannot_use_combo_opioid_with_apap_asa_ibu": True,
        "migraine_prophylaxis_and_triptans_or_contraindicated": True,  # unused on pain path
    }, **updates)


def migraine(**updates):
    return dict({
        "pa_override_population": "standard_outpatient_path",
        "age_years": 18,
        "first_line_medication_suboptimal": True,
        "indication": "migraine",
        "cannot_use_combo_opioid_with_apap_asa_ibu": True,  # unused on migraine path
        "migraine_prophylaxis_and_triptans_or_contraindicated": True,
    }, **updates)


def test_branches_override_catalog():
    assert evaluate(pack(), pain()).decision == "pass"
    assert evaluate(pack(), migraine()).decision == "pass"
    assert evaluate(pack(), pain(age_years=17)).decision == "fail"
    assert evaluate(pack(), pain(cannot_use_combo_opioid_with_apap_asa_ibu=False)).decision == "fail"
    assert evaluate(pack(), migraine(migraine_prophylaxis_and_triptans_or_contraindicated=False)).decision == "fail"
    override = {"pa_override_population": "hospice_or_cancer_or_ltc"}
    assert evaluate(pack(), override).decision == "pass"
    ct = json.loads((BASE / "criteria_text/stadol.json").read_text())
    assert ct["ocr_status"] == "tesseract_recovered"
    assert "Butorphanol" in ct["extracted_text"] or "butorphanol" in ct["extracted_text"].lower()
    detail = drug_detail("stadol")
    assert detail["can_evaluate"]
    coerced = pain(first_line_medication_suboptimal="yes", cannot_use_combo_opioid_with_apap_asa_ibu="yes")
    assert evaluate(pack(), _coerce_patient(coerced)).decision == "pass"
    catalog = load_rule_pack_catalog()
    assert catalog["stadol"]["encoding_status"] == "partial"
    assert sum(x["encoding_status"] == "text_only" for x in catalog.values()) == 0
    assert (BASE / "stadol.json").read_bytes() == (BASE / "rule_packs/stadol.json").read_bytes()
