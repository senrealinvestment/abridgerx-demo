"""Catalog 100%: 198 partial / 0 text_only after finishing remaining eight."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engine.evaluate import evaluate
from ui.loaders import load_rule_pack_catalog

BASE = ROOT / "data/alaska/parsed"

FINISHED = {
    "000-unit": "alias",
    "hemophilia": "alias",
    "atypical-antipsychotic-therapeutic-duplication": "encoded",
    "bactroban-cream": "encoded",
    "fexmid": "ocr",
    "soma": "ocr",
    "stadol": "ocr",
    "ergocalciferol": "ocr",
}


def test_zero_text_only_and_aliases_evaluate():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 198
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 0
    assert set(FINISHED) <= set(catalog)
    for slug in FINISHED:
        assert catalog[slug]["encoding_status"] == "partial"
        assert catalog[slug].get("criteria"), slug
    # aliases share criteria with canonical packs
    assert catalog["000-unit"]["criteria"] == catalog["vitamin-d-50"]["criteria"]
    assert catalog["hemophilia"]["criteria"] == catalog["clotting-factor"]["criteria"]
    assert "RETIRED ALIAS" in " ".join(catalog["000-unit"]["notes"])
    assert "RETIRED ALIAS" in " ".join(catalog["hemophilia"]["notes"])
    # OCR packs recovered
    for slug in ["fexmid", "soma", "stadol", "ergocalciferol"]:
        ct = json.loads((BASE / f"criteria_text/{slug}.json").read_text())
        assert ct.get("ocr_status") == "tesseract_recovered"
        assert (ct.get("extracted_text") or "").strip()
    status = json.loads((BASE / "ENCODING_STATUS.json").read_text())
    assert (status["encoding_partial"], status["encoding_text_only"], status["next_candidate"]) == (198, 0, None)
    assert status["partial_slugs"] == sorted(k for k, p in catalog.items() if p["encoding_status"] == "partial")
    assert json.loads((BASE / "rule_packs_all.json").read_text()) == catalog
    with gzip.open(BASE / "rule_packs_all.json.gz", "rt") as stream:
        assert json.load(stream) == catalog
    for name in ["ENCODING_STATUS.json", "ENCODING_STATUS.md"]:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
    # alias evaluate is not encoding_incomplete
    vit_pass = {
        "indication": "hypoparathyroidism",
        "not_dietary_supplement": True,
        "failed_1000_2000iu_daily_ge_6mo_labs_submitted": True,
    }
    assert evaluate(catalog["000-unit"], vit_pass).decision == "pass"
