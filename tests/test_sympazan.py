"""Sympazan / Onfi source criteria, UI, and single-pack catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/sympazan.json').read_text())
FACTS = dict(indication='lennox_gastaut_syndrome', age_years=2,
             current_other_aed=True, failed_generic_clobazam=True)


def test_eligible():
    assert evaluate(PACK, FACTS).decision == 'pass'


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['other', 'epilepsy', 'dravet_syndrome', 'yes', True, False])
def test_closed_indication(value):
    assert evaluate(PACK, dict(FACTS, indication=value)).decision == 'fail'


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (1.99, 'fail'), (2, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


@pytest.mark.parametrize('fact', ['current_other_aed', 'failed_generic_clobazam'])
def test_unmet_gate(fact):
    result = evaluate(PACK, dict(FACTS, **{fact: False}))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {fact}
    assert result.citations


def test_ui():
    fields = {f['key']: f for f in drug_detail('sympazan')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == ['lennox_gastaut_syndrome']
    for fact, field in fields.items():
        assert field['type'] == 'select'
        if fact != 'indication':
            assert field['when'] == dict(fact='indication', eq='lennox_gastaut_syndrome')
        for option in field['options']:
            value = option['value']
            assert evaluate(PACK, _coerce_patient(dict(FACTS, **{fact: value}))).decision == ('fail' if value in {'no', '0'} else 'pass')


def test_source_and_notes_only_limits():
    assert PACK['source']['effective_date'] == '2019-11-20'
    assert len(PACK['criteria']) == 4
    assert {f for c in PACK['criteria'] for f in c['required_facts']} == set(FACTS)
    assert 'documentation of current and prior therapies' in PACK['fact_ui']['current_other_aed']['label']
    notes = ' '.join(PACK['notes'])
    for text in ['6 months', '2 doses/day', '40 mg/day', 'Version 3', '09/2/2014', '9/20/2019', 'Schedule IV', '5/10/20 mg', '10/20 mg', '2.5 mg/mL']:
        assert text in notes
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK


def test_catalog():
    catalog = load_rule_pack_catalog()
    assert catalog['sympazan'] == PACK
    assert PACK['encoding_status'] == 'partial'
    assert (BASE / 'sympazan.json').read_bytes() == (BASE / 'rule_packs/sympazan.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 188
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 10
    for root in (BASE, BASE.parent):
        status = json.loads((root / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (188, 10)
        assert status['next_candidate'] == 'hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc'
        assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for ext in ('json', 'md'):
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()
    assert catalog['hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc']['encoding_status'] == 'text_only'
    assert catalog['hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc']['criteria'] == []
    assert evaluate(catalog['hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc'], FACTS).decision == 'need_info'
