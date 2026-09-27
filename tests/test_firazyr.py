"""Firazyr source eligibility, closed controls, and catalog integration."""
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
INDICATION = 'hereditary_angioedema_acute_attack'
STEP = 'prophylactic_therapy_status'


def pack():
    return json.loads((BASE / 'rule_packs/firazyr.json').read_text())


def facts(**changes):
    return dict({'indication': INDICATION, 'age_years': 18,
                 'hae_diagnosis_by_immunologist': True,
                 STEP: 'on_prophylactic_therapy'}, **changes)


@pytest.mark.parametrize('step', ['on_prophylactic_therapy', 'contraindicated', 'response_failure'])
@pytest.mark.parametrize('age', [18, 19, 80])
def test_approval_paths(step, age):
    assert evaluate(pack(), facts(**{STEP: step, 'age_years': age})).decision == 'pass'


@pytest.mark.parametrize('key,value', [
    ('age_years', 17), ('age_years', 17.9), ('age_years', 0),
    ('hae_diagnosis_by_immunologist', False),
    *[('indication', v) for v in ['hae_routine_prophylaxis', 'hae', 'other', 'yes', True, False]],
    *[(STEP, v) for v in ['not_met', 'yes', True, False, 'unknown']],
])
def test_denials(key, value):
    result = evaluate(pack(), facts(**{key: value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [
        'indication_fda_labeled' if key == 'indication' else key]


def test_missing_and_null():
    for key in facts():
        for missing in [True, False]:
            patient = facts()
            if missing:
                del patient[key]
            else:
                patient[key] = None
            result = evaluate(pack(), patient)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
    assert set(evaluate(pack(), {}).missing_facts) == set(facts())


def test_ui():
    detail = drug_detail('firazyr')
    assert detail['can_evaluate'] and detail['criteria_text']['extracted_text']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    for key in ['indication', STEP, 'hae_diagnosis_by_immunologist']:
        assert fields[key]['type'] == 'select' and not fields[key].get('free_text')
        assert fields[key]['options'] == pack()['fact_ui'][key]['options']
    assert [o['value'] for o in fields['indication']['options']] == [INDICATION]
    for option in fields[STEP]['options']:
        patient = _coerce_patient(facts(**{STEP: option['value'], 'age_years': '18',
                                        'hae_diagnosis_by_immunologist': 'yes'}))
        assert evaluate(pack(), patient).decision == ('fail' if option['value'] == 'not_met' else 'pass')
    assert evaluate(pack(), _coerce_patient(facts(hae_diagnosis_by_immunologist='no'))).decision == 'fail'


def test_source_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='Firazyr', generic_name='icatibant', therapeutic_class='bradykinin-b2-antagonist')
    assert p['source']['effective_date'] == '2023-01-02'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/dxeln3fy/firazyr.pdf'
    assert p['encoding_status'] == 'partial' and 'inferred_required_facts' not in p
    assert len(p['criteria']) == 4
    assert {c['predicate']['fact'] for c in p['criteria']} == set(facts())
    age = next(c for c in p['criteria'] if c['id'] == 'age_years')
    assert age['predicate'] == dict(op='gte', fact='age_years', value=18)
    notes = ' '.join(p['notes'])
    for term in ['Version 1', '3/2/2012', '03/16/2012', 'letter of medical necessity',
                 'date of service', '3 units', 'Refills', 'Emergency Room or Hospital intervention', 'manual review']:
        assert term in notes
    catalog = load_rule_pack_catalog()
    assert catalog['firazyr'] == p
    assert p['alternatives'] == ['berinert']
    assert 'firazyr' in catalog['berinert']['alternatives']
    assert catalog['crenessity']['encoding_status'] == 'partial'
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 115
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 83
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (115, 83)
    assert status['next_candidate'] == 'verquvo'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['firazyr', 'berinert']:
        assert (BASE / f'{name}.json').read_bytes() == (BASE / f'rule_packs/{name}.json').read_bytes()
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
