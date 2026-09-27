"""Adcirca AK Medicaid criteria and catalog integration from the Version 2 PDF."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.evaluate import evaluate  # noqa: E402
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog  # noqa: E402


def load_pack():
    return json.loads((ROOT / "data/alaska/parsed/adcirca.json").read_text())


def _base(**extra):
    facts = {
        "indication": "pah_who_group_i",
        "not_taking_nitrates": True,
        "sildenafil_step": "tried_generic_sildenafil",
    }
    facts.update(extra)
    return facts


def _assert_fail(clause, **extra):
    result = evaluate(load_pack(), _base(**extra))
    assert result.decision == "fail", result
    assert clause in {c["id"] for c in result.failed_clauses}, result


def test_encoding_partial_and_pdl_non_preferred():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert pack["pdl_status"] == "non_preferred"
    assert pack["drug"] == {
        "name": "Adcirca", "generic_name": "tadalafil",
        "therapeutic_class": "pulmonary-arterial-hypertension",
    }
    assert pack["source"]["effective_date"] == "2023-06-01"
    assert pack["source"]["citation"] == "https://health.alaska.gov/media/aqvmnzsx/adcirca.pdf"
    assert len(pack["criteria"]) == 3
    assert pack["max_units"]["quantity"] is None
    assert "2 tablets per day" in pack["max_units"]["notes"]
    assert any("09/19/2014" in note for note in pack["notes"])
    assert any("up to 1 year" in note for note in pack["notes"])


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("adcirca")
    assert detail
    field = next(f for f in detail["fact_fields"] if f["key"] == "indication")
    assert field["type"] == "select"
    assert field["option_source"] == "fact_ui"
    assert field["options"] == [{
        "value": "pah_who_group_i",
        "label": "Pulmonary Arterial Hypertension (PAH, WHO Group I)",
    }]
    for invalid in ["yes", "no", "unknown", "pah_who_group_ii", "asthma"]:
        _assert_fail("indication_fda_labeled", indication=invalid)


def test_selects_only_and_no_invented_age_gate():
    pack = load_pack()
    detail = drug_detail("adcirca")
    assert detail
    assert set(pack["fact_ui"]) == set(_base())
    assert {f["key"] for f in detail["fact_fields"]} == set(_base())
    for field in detail["fact_fields"]:
        assert field["type"] == "select", field
        assert field.get("free_text") is not True
        assert field["option_source"] == "fact_ui"
        assert field.get("options"), field
    assert {o["value"] for o in pack["fact_ui"]["not_taking_nitrates"]["options"]} == {"yes", "no"}


def test_pass_both_sildenafil_paths_without_age():
    for step in ["tried_generic_sildenafil", "allergy_hypersensitivity_all_generic_sildenafil"]:
        result = evaluate(load_pack(), _base(sildenafil_step=step))
        assert result.decision == "pass", result
        assert not result.missing_facts


def test_fail_nitrates_even_with_sildenafil_exception():
    for step in ["tried_generic_sildenafil", "allergy_hypersensitivity_all_generic_sildenafil"]:
        _assert_fail("not_taking_nitrates", not_taking_nitrates=False, sildenafil_step=step)


def test_sildenafil_exception_does_not_bypass_indication():
    _assert_fail("indication_fda_labeled", indication="pah_who_group_ii",
                 sildenafil_step="allergy_hypersensitivity_all_generic_sildenafil")


def test_fail_sildenafil_step_neither():
    for step in ["neither", "unknown", "yes"]:
        _assert_fail("sildenafil_step", sildenafil_step=step)


def test_missing_facts_need_info():
    for fact in _base():
        facts = _base()
        del facts[fact]
        result = evaluate(load_pack(), facts)
        assert result.decision == "need_info", result
        assert result.missing_facts == [fact], result


def test_catalog_mirrors_and_status_load():
    base = ROOT / "data/alaska/parsed"
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    assert catalog["adcirca"] == pack
    assert get_rule_pack("adcirca") == ("adcirca", pack)
    assert json.loads((base / "rule_packs/adcirca.json").read_text()) == pack
    assert catalog == {
        path.stem: json.loads(path.read_text())
        for path in (base / "rule_packs").glob("*.json")
    }
    with gzip.open(base / "rule_packs_all.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 50
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 148
    assert pack["alternatives"] == []
    assert catalog["revatio"]["encoding_status"] == "text_only"
    status = json.loads((base / "ENCODING_STATUS.json").read_text())
    assert status["encoding_partial"] == 50
    assert status["encoding_text_only"] == 148
    assert status["partial_slugs"] == sorted(
        slug for slug, p in catalog.items() if p["encoding_status"] == "partial"
    )
    assert json.loads((base.parent / "ENCODING_STATUS.json").read_text()) == status
    assert (base.parent / "ENCODING_STATUS.md").read_text() == (base / "ENCODING_STATUS.md").read_text()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("adcirca tests ok")
