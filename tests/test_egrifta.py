"""Egrifta AK Medicaid criteria and catalog integration from the Version 1 PDF."""

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
    return json.loads((ROOT / "data/alaska/parsed/egrifta.json").read_text())


def _base(**extra):
    facts = {
        "indication": "hiv_lipodystrophy_excess_abdominal_fat",
        "hiv_positive": True,
    }
    facts.update(extra)
    return facts


def _assert_fail(clause, **extra):
    result = evaluate(load_pack(), _base(**extra))
    assert result.decision == "fail", result
    assert clause in {c["id"] for c in result.failed_clauses}, result


def test_metadata_and_only_source_criteria():
    pack = load_pack()
    assert pack["encoding_status"] == "partial"
    assert pack["pdl_status"] == "unknown"
    assert pack["drug"] == {
        "name": "Egrifta", "generic_name": "tesamorelin",
        "therapeutic_class": "growth-hormone-releasing-factor",
    }
    assert pack["source"]["effective_date"] == "2025-03-01"
    assert pack["source"]["citation"] == "https://health.alaska.gov/media/4mhdc51p/egrifta.pdf"
    assert pack["source"]["criteria_pdf"] == "data/alaska/raw/egrifta.pdf"
    assert "inferred_required_facts" not in pack
    assert [c["id"] for c in pack["criteria"]] == ["indication_fda_labeled", "hiv_positive"]
    assert pack["criteria"][1]["predicate"] == {"op": "eq", "fact": "hiv_positive", "value": True}
    assert pack["max_units"]["quantity"] is None
    assert pack["max_units"]["days_supply"] == 30
    notes = " ".join(pack["notes"])
    for text in ["11/18/2011", "up to 3 months", "clinical improvement of lipodystrophy",
                 "not indicated for weight loss management", "cardiovascular benefit and safety",
                 "no data to support compliance with anti-retroviral therapies"]:
        assert text in notes


def test_indication_closed_list_never_yes_no_unknown():
    detail = drug_detail("egrifta")
    assert detail and detail["can_evaluate"]
    field = next(f for f in detail["fact_fields"] if f["key"] == "indication")
    assert field["type"] == "select"
    assert field["option_source"] == "fact_ui"
    assert field["options"] == [{
        "value": "hiv_lipodystrophy_excess_abdominal_fat",
        "label": "Reduction of excess abdominal fat in HIV-infected patients with lipodystrophy",
    }]
    for invalid in ["yes", "no", "unknown", True, False, "weight_loss", "hiv"]:
        _assert_fail("indication_fda_labeled", indication=invalid)


def test_selects_only_and_no_extra_gates():
    pack = load_pack()
    detail = drug_detail("egrifta")
    assert detail
    assert set(pack["fact_ui"]) == set(_base())
    assert {f["key"] for f in detail["fact_fields"]} == set(_base())
    for field in detail["fact_fields"]:
        assert field["type"] == "select", field
        assert field.get("free_text") is not True
        assert field["option_source"] == "fact_ui"
        assert field.get("options"), field
    assert pack["fact_ui"]["hiv_positive"]["options"] == [
        {"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"},
    ]


def test_pass_hiv_yes():
    result = evaluate(load_pack(), _base())
    assert result.decision == "pass", result
    assert not result.missing_facts


def test_fail_hiv_no():
    _assert_fail("hiv_positive", hiv_positive=False)


def test_ui_yes_no_coercion():
    from ui.app import _coerce_patient

    for answer, expected in [("yes", "pass"), ("no", "fail")]:
        result = evaluate(load_pack(), _coerce_patient(_base(hiv_positive=answer)))
        assert result.decision == expected, result


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
    assert catalog["egrifta"] == pack
    assert get_rule_pack("egrifta") == ("egrifta", pack)
    assert json.loads((base / "rule_packs/egrifta.json").read_text()) == pack
    assert catalog == {
        path.stem: json.loads(path.read_text())
        for path in (base / "rule_packs").glob("*.json")
    }
    with gzip.open(base / "rule_packs_all.json.gz", "rt", encoding="utf-8") as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p["encoding_status"] == "partial" for p in catalog.values()) == 114
    assert sum(p["encoding_status"] == "text_only" for p in catalog.values()) == 84
    assert pack["alternatives"] == []
    status = json.loads((base / "ENCODING_STATUS.json").read_text())
    assert status["encoding_partial"] == 114
    assert status["encoding_text_only"] == 84
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
    print("egrifta tests ok")
