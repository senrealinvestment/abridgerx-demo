"""Insulin pen POS attestations, closed indication and catalog integration."""
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
SLUG = 'insulin-pens'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
INDICATION = 'diabetes_insulin_pen_use'
FACTS = [
    'original_sealed_carton_or_documented_professional_judgment',
    'directions_mathematically_useful_or_prescriber_contact_documented',
    'day_supply_le_34_or_correct_days_then_capped',
]


@pytest.mark.parametrize('values', list(product([True, False, None, 'absent'], repeat=3)))
def test_required_attestations(values):
    patient = {'indication': INDICATION}
    patient.update({f: v for f, v in zip(FACTS, values) if v != 'absent'})
    result = evaluate(PACK, patient)
    missing = [f for f in FACTS if patient.get(f) is None]
    assert result.decision == ('need_info' if missing else 'fail' if False in values else 'pass')
    assert result.missing_facts == missing
    assert [c['id'] for c in result.failed_clauses] == [f for f, v in zip(FACTS, values) if v is False]


@pytest.mark.parametrize('indication', ['other', 'diabetes', '', None, 'absent'])
def test_closed_indication(indication):
    patient = {} if indication == 'absent' else {'indication': indication}
    expected = 'need_info' if indication in [None, 'absent'] else 'fail'
    for facts in [{}, dict.fromkeys(FACTS, True)]:
        result = evaluate(PACK, {**patient, **facts})
        assert result.decision == expected
        assert result.missing_facts == (['indication'] if expected == 'need_info' else [])


def test_ui_and_no_extra_gates():
    fields = {f['key']: f for f in drug_detail(SLUG)['fact_fields']}
    assert set(fields) == {'indication', *FACTS}
    assert {o['value'] for o in fields['indication']['options']} == {INDICATION, 'other'}
    assert [c['id'] for c in PACK['criteria']] == ['indication', *FACTS]
    for fact, clause in zip(FACTS, PACK['criteria'][1:]):
        assert fields[fact]['when'] == clause['when'] == {'fact': 'indication', 'eq': INDICATION}
        assert clause['predicate'] == {'op': 'eq', 'fact': fact, 'value': True}
        patient = _coerce_patient({'indication': INDICATION, **dict.fromkeys(FACTS, 'yes')})
        assert evaluate(PACK, patient).decision == 'pass'
        patient.update(_coerce_patient({fact: 'no'}))
        assert evaluate(PACK, patient).decision == 'fail'


def test_metadata_and_catalog():
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2022-05-01'
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for phrase in ['Version 1', '10/26/2020', 'Approval: pending', 'Effective: pending', '2022-05-01', 'point-of-sale', 'medication and dosing error', 'not subject to recovery', 'authorizing agent, date, time and pharmacist initials', 'October 13, 2020', '34-day', 'rejection', 'captured and retained']:
        assert phrase in notes
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE / 'rule_packs').glob('*.json')}
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 190
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 8
    assert catalog['hemophilia']['encoding_status'] == 'text_only'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (190, 8, None)
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
