"""Relistor approval/denial mirrors, missing facts, UI and catalog integrity."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/relistor.json').read_text())
INDICATIONS = ['opioid_induced_constipation_chronic_noncancer_pain',
               'opioid_induced_constipation_advanced_illness_palliative']
GOOD = dict(indication=INDICATIONS[0], age_years=18, opioids_longer_than_4_weeks=True,
            no_mechanical_gi_obstruction=True, failed_two_laxative_therapies=True)


@pytest.mark.parametrize('indication', INDICATIONS)
def test_eligible(indication):
    assert evaluate(PACK, dict(GOOD, indication=indication)).decision == 'pass'


@pytest.mark.parametrize('indication', INDICATIONS)
@pytest.mark.parametrize('fact,value', [('age_years', 17.99), ('indication', 'other'),
    ('opioids_longer_than_4_weeks', False), ('no_mechanical_gi_obstruction', False),
    ('failed_two_laxative_therapies', False)])
def test_denials(indication, fact, value):
    patient = dict(GOOD, indication=indication)
    patient[fact] = value
    result = evaluate(PACK, patient)
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [fact]
    assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('indication', INDICATIONS)
@pytest.mark.parametrize('fact', GOOD)
@pytest.mark.parametrize('null', [False, True])
def test_missing(indication, fact, null):
    patient = dict(GOOD, indication=indication)
    if null:
        patient[fact] = None
    else:
        del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['other', 'opioid_induced_constipation', 'chronic_constipation', 'yes', True, False])
def test_closed_indication(value):
    assert evaluate(PACK, dict(GOOD, indication=value)).decision == 'fail'


def test_gates_and_ui():
    assert evaluate(PACK, {}).missing_facts == ['indication']
    assert evaluate(PACK, {'indication': 'other'}).decision == 'fail'
    fields = {f['key']: f for f in drug_detail('relistor')['fact_fields']}
    assert set(fields) == set(GOOD)
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    for fact, field in fields.items():
        assert field['type'] == 'select'
        if fact != 'indication':
            assert field['when'] == {'fact': 'indication', 'in': INDICATIONS}
        for option in field['options']:
            patient = _coerce_patient(dict(GOOD, **{fact: option['value']}))
            expected = fact == 'indication' or patient[fact] == GOOD[fact]
            assert evaluate(PACK, patient).decision == ('pass' if expected else 'fail')


def test_metadata_and_catalog():
    assert PACK['source']['effective_date'] == '2019-11-20'
    assert PACK['drug']['generic_name'] == 'methylnaltrexone bromide'
    assert PACK['encoding_status'] == 'partial'
    assert len(PACK['criteria']) == 5
    assert {f for c in PACK['criteria'] for f in c['required_facts']} == set(GOOD)
    assert 'inferred_required_facts' not in PACK
    assert PACK['max_units'] is None
    notes = ' '.join(PACK['notes'])
    for phrase in ['8mg/0.4ml syringe', '12mg/0.6ml kit', '12mg/0.6ml syringe',
                   '12mg/0.6ml vial', '150mg tablet', 'tablet for OIC', 'injection for OIC',
                   'gastrointestinal perforation', 'severe or persistent diarrhea',
                   'opioid withdrawal', '4 months', '30-day supply at FDA approved dosage']:
        assert phrase in notes
    assert (BASE/'relistor.json').read_bytes() == (BASE/'rule_packs/relistor.json').read_bytes()
    catalog = json.loads((BASE/'rule_packs_all.json').read_text())
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE/'rule_packs').glob('*.json')}
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 187
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 11
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (187, 11, 'genotypes')
    assert 'relistor' in status['partial_slugs']
    assert catalog['genotypes']['encoding_status'] == 'text_only'
    assert catalog['genotypes']['criteria'] == []
