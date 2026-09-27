"""Korlym source criteria, closed choices, and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/korlym.json').read_text())
FACTS = dict(
    indication='endogenous_cushings_hyperglycemia', age_years=18,
    cushings_syndrome=True, diabetes_or_glucose_intolerance='type_2_diabetes',
    surgery_status='failed_surgery',
)


@pytest.mark.parametrize('diagnosis', ['type_2_diabetes', 'glucose_intolerance'])
@pytest.mark.parametrize('surgery', ['failed_surgery', 'not_surgery_candidate'])
def test_eligible_branches(diagnosis, surgery):
    result = evaluate(PACK, dict(FACTS, diabetes_or_glucose_intolerance=diagnosis, surgery_status=surgery))
    assert result.decision == 'pass'
    assert result.citations


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', 'other', True, False,
                                  'type_2_diabetes', 'cushings_disease', 'cushings_syndrome'])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (17, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


def test_ui_options_and_denials():
    fields = {f['key']: f for f in drug_detail('korlym')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == ['endogenous_cushings_hyperglycemia']
    assert all('when' not in c for c in PACK['criteria'])
    for fact, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{fact: value})))
            denied = value in {'no', '0', 'neither'}
            assert result.decision == ('fail' if denied else 'pass'), (fact, value)
            assert {c['id'] for c in result.failed_clauses} == (
                {'minimum_age' if fact == 'age_years' else fact} if denied else set())


@pytest.mark.parametrize('fact', ['diabetes_or_glucose_intolerance', 'surgery_status'])
@pytest.mark.parametrize('value', ['yes', 'unknown', True, False])
def test_closed_approval_choices(fact, value):
    assert evaluate(PACK, dict(FACTS, **{fact: value})).decision == 'fail'


def test_metadata_notes_and_catalog():
    assert PACK['drug'] == dict(name='Korlym', generic_name='mifepristone', therapeutic_class='cortisol-receptor-blocker')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2013-01-18'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/2hwgnaft/korlym-pa.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None
    assert PACK['alternatives'] == ['isturisa']
    assert len(PACK['criteria']) == 5
    assert 'inferred_required_facts' not in PACK
    assert {f for c in PACK['criteria'] for f in c['required_facts']} == set(FACTS)
    for phrase in ['Version 1', '12/11/2012', '01/18/2013', 'approval date',
                   'Limitations of Use', 'unrelated to endogenous', '3 months', '9 months',
                   'clinical improvement', '30-day supply', '1200 mg once daily',
                   '20 mg/kg/day', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])
    assert (BASE / 'korlym.json').read_bytes() == (BASE / 'rule_packs/korlym.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['isturisa']['alternatives'] == ['korlym']
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 171
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 27
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (171, 27)
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'extended-release'
    assert (BASE / 'ENCODING_STATUS.md').read_bytes() == (BASE.parent / 'ENCODING_STATUS.md').read_bytes()


def test_next_pack_remains_unencoded():
    pack = load_rule_pack_catalog()['extended-release']
    assert pack['encoding_status'] == 'text_only'
    assert pack['criteria'] == []
    assert evaluate(pack, {}).decision == 'need_info'
