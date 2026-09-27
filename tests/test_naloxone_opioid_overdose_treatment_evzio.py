"""Evzio closed indication, alternative approval paths, and catalog integration."""
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
SLUG = 'naloxone-opioid-overdose-treatment-evzio'
NEXT = 'statins'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
INDICATION = 'opioid_overdose_emergency'
FACTS = ['narcan_nasal_spray_intolerance', 'narcan_nasal_spray_cannot_be_used']


@pytest.mark.parametrize('left,right', list(product([True, False, None, 'absent'], repeat=2)))
def test_alternative_approval_truth_table(left, right):
    patient = {'indication': INDICATION}
    patient.update({f: v for f, v in zip(FACTS, [left, right]) if v != 'absent'})
    result = evaluate(PACK, patient)
    expected = 'pass' if True in [left, right] else 'fail' if left is False and right is False else 'need_info'
    assert result.decision == expected
    assert result.missing_facts == ([f for f in FACTS if patient.get(f) is None] if expected == 'need_info' else [])
    if expected == 'fail':
        assert [c['id'] for c in result.failed_clauses] == ['narcan_nasal_spray_exception']


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
    assert PACK['source']['effective_date'] == '2016-10-03'
    assert 'inferred_required_facts' not in PACK
    assert len(PACK['criteria']) == 2
    notes = ' '.join(PACK['notes'])
    for phrase in ['0.4 mg/0.4 mL', 'Version 1', '1/22/2016', '10/3/2016', '6 months', '1 year', '1 box (2 auto-injectors) per fill', 'not a substitute for emergency medical care', 'CDC']:
        assert phrase in notes
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE / 'rule_packs').glob('*.json')}
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 182
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 16
    assert catalog[NEXT]['encoding_status'] == 'text_only'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (182, 16, NEXT)
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
