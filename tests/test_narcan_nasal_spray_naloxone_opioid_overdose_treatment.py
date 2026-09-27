"""Narcan closed indication, POS approval attestations, and catalog integration."""
import gzip
import json
import sys
from itertools import product
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail

BASE = ROOT / 'data/alaska/parsed'
SLUG = 'narcan-nasal-spray-naloxone-opioid-overdose-treatment'
NEXT = None
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
INDICATION = 'opioid_overdose_emergency'
FACTS = ['narcan_fills_within_365d_lt_3', 'narcan_fills_ge_3_pharmacist_override_completed']


@pytest.mark.parametrize('left,right', list(product([True, False, None, 'absent'], repeat=2)))
def test_alternative_approval_truth_table(left, right):
    patient = {'indication': INDICATION}
    patient.update({f: v for f, v in zip(FACTS, [left, right]) if v != 'absent'})
    result = evaluate(PACK, patient)
    expected = 'pass' if True in [left, right] else 'fail' if left is False and right is False else 'need_info'
    assert result.decision == expected
    assert result.missing_facts == ([f for f in FACTS if patient.get(f) is None] if expected == 'need_info' else [])
    if expected == 'fail':
        assert [c['id'] for c in result.failed_clauses] == ['pos_approval']


@pytest.mark.parametrize('indication', ['other', 'overdose_risk', '', None, 'absent'])
def test_closed_indication(indication):
    patient = {} if indication == 'absent' else {'indication': indication}
    result = evaluate(PACK, patient)
    assert result.decision == ('need_info' if indication in [None, 'absent'] else 'fail')
    assert result.missing_facts == (['indication'] if indication in [None, 'absent'] else [])
    patient.update(dict.fromkeys(FACTS, True))
    assert evaluate(PACK, patient).decision == result.decision


def test_ui_fields_and_coercion():
    fields = {f['key']: f for f in drug_detail(SLUG)['fact_fields']}
    assert set(fields) == {'indication', *FACTS}
    assert {o['value'] for o in fields['indication']['options']} == {INDICATION, 'other'}
    for fact in FACTS:
        assert fields[fact]['when'] == {'fact': 'indication', 'eq': INDICATION}
        patient = _coerce_patient({'indication': INDICATION, fact: 'yes'})
        assert evaluate(PACK, patient).decision == 'pass'


def test_metadata_notes_and_catalog():
    assert PACK['encoding_status'] == 'partial'
    assert PACK['drug']['generic_name'] == 'naloxone HCl'
    assert PACK['source']['effective_date'] == '2016-09-07'
    assert 'inferred_required_facts' not in PACK
    assert len(PACK['criteria']) == 2
    notes = ' '.join(PACK['notes'])
    for phrase in ['4 mg/0.1 mL', 'Version 1', '1/22/2016', '9/7/2016', 'point-of-sale', 'rolling 365', 'NCPDP 75', 'opioid prescriber (if different)', 'whether or not the regimen changed', 'within 3 days', 'PATC = 5', '461-EU', 'Alaska Medicaid on request', 'non-opioid analgesic', 'benzodiazepines, alcohol', 'not a substitute for emergency medical care', 'Mechanism', 'Companion Evzio']:
        assert phrase in notes
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE / 'rule_packs').glob('*.json')}
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 198
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 0
    assert catalog['hemophilia']['encoding_status'] == 'partial'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (198, 0, NEXT)
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')


def test_no_invented_clinical_steps():
    assert [c['id'] for c in PACK['criteria']] == ['indication', 'pos_approval']
    assert PACK['criteria'][1]['when'] == {'fact': 'indication', 'eq': INDICATION}
    assert PACK['criteria'][1]['predicate'] == {
        'op': 'any', 'args': [{'op': 'eq', 'fact': f, 'value': True} for f in FACTS]
    }
    for fact in FACTS:
        patient = _coerce_patient({'indication': INDICATION, fact: 'no'})
        assert patient[fact] is False
        assert evaluate(PACK, patient).decision == 'need_info'
