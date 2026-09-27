"""Rybix ODT approval conjunction, formulation alternatives and catalog integrity."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/rybix-odt.json').read_text())
IND = 'moderate_to_moderately_severe_pain'
DOSE = 'cumulative_tramadol_dose_le_400mg_day'
IR = 'failed_tramadol_ir'
ODT = 'unable_to_swallow_or_odt_rationale'
FACTS = dict(indication=IND, age_years=17, **{DOSE: True})


@pytest.mark.parametrize('ir', [True, False, None])
@pytest.mark.parametrize('odt', [True, False, None])
def test_formulation_truth_table(ir, odt):
    expected = 'pass' if True in (ir, odt) else 'need_info' if None in (ir, odt) else 'fail'
    result = evaluate(PACK, dict(FACTS, **{IR: ir, ODT: odt}))
    assert result.decision == expected
    if expected == 'need_info':
        assert set(result.missing_facts) == {f for f, v in [(IR, ir), (ODT, odt)] if v is None}


@pytest.mark.parametrize('branch', [IR, ODT])
@pytest.mark.parametrize('key,value,expected', [('age_years', 16.99, 'fail'), ('age_years', 17, 'pass'), ('age_years', 18, 'pass'), (DOSE, False, 'fail')])
def test_shared_requirements(branch, key, value, expected):
    assert evaluate(PACK, dict(FACTS, **{branch: True, key: value})).decision == expected


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing_shared_facts(key, omit):
    facts = dict(FACTS, **{IR: True, key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('indication', ['other', 'severe_pain', '', True, False])
def test_closed_indication(indication):
    result = evaluate(PACK, {'indication': indication})
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']
    assert result.citations == [PACK['source']['citation']]


def test_ui():
    assert evaluate(PACK, {}).missing_facts == ['indication']
    detail = drug_detail('rybix-odt')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(FACTS) | {IR, ODT}
    for key in (set(FACTS) | {IR, ODT}) - {'indication'}:
        assert PACK['fact_ui'][key]['when'] == {'fact': 'indication', 'in': [IND]}
    for branch in [IR, ODT]:
        facts = dict(indication=IND, age_years='17', **{DOSE: 'yes', branch: 'yes'})
        assert evaluate(PACK, _coerce_patient(facts)).decision == 'pass'


def test_source_and_notes():
    source = json.loads((BASE / 'criteria_text/rybix-odt.json').read_text())
    assert PACK['source']['citation'] == source['source_url']
    assert PACK['source']['effective_date'] == '2020-01-06'
    assert len(PACK['criteria']) == 4
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    for text in ['50 mg', '6 months', '30-day supply', '8 doses/day', '400 mg/day', '300 mg/day', '2 doses/day', 'Version 1', '3/20/2013', '4/19/2013']:
        assert text in ' '.join(PACK['notes'])


def test_catalog():
    catalog = load_rule_pack_catalog()
    assert catalog['rybix-odt'] == PACK
    assert PACK['encoding_status'] == 'partial'
    assert (BASE / 'rybix-odt.json').read_bytes() == (BASE / 'rule_packs/rybix-odt.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 187
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 11
    for root in [BASE, BASE.parent]:
        status = json.loads((root / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (187, 11, 'genotypes')
        assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for ext in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()
    for slug in ['genotypes', 'fexmid', 'soma', 'stadol', 'ergocalciferol']:
        assert catalog[slug]['encoding_status'] == 'text_only'
