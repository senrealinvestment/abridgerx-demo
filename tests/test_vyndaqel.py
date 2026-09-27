"""Vyndaqel: source-specific gates, UI choices, missing facts and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/vyndaqel.json').read_text())
FACTS = dict(
    indication='attr_cardiomyopathy', age_years=18,
    prescriber_specialty='cardiologist_or_consult',
    attr_confirmation='cardiac_biopsy_amyloid_deposits',
    cardiomyopathy_hf_symptoms='present',
    no_liver_or_heart_transplant=True, nyha_class='i_ii_or_iii',
)


@pytest.mark.parametrize('fact,allowed,denied', [
    ('attr_confirmation', ['cardiac_biopsy_amyloid_deposits', 'ttr_mutation_genetic_or_wild_type'], ['not_confirmed']),
    ('prescriber_specialty', ['cardiologist_or_consult'], ['none']),
    ('cardiomyopathy_hf_symptoms', ['present'], ['absent']),
    ('nyha_class', ['i_ii_or_iii'], ['iv']),
])
def test_clinical_gates(fact, allowed, denied):
    assert {o['value'] for o in PACK['fact_ui'][fact]['options']} == set(allowed + denied)
    for value in allowed + denied:
        result = evaluate(PACK, dict(FACTS, **{fact: value}))
        assert result.decision == ('pass' if value in allowed else 'fail')
        assert {c['id'] for c in result.failed_clauses} == (set() if value in allowed else {fact})
        assert result.citations


@pytest.mark.parametrize('value,decision', [(True, 'pass'), (False, 'fail'), ('yes', 'pass'), ('no', 'fail')])
def test_transplant(value, decision):
    patient = _coerce_patient(dict(FACTS, no_liver_or_heart_transplant=value))
    result = evaluate(PACK, patient)
    assert result.decision == decision
    assert {c['id'] for c in result.failed_clauses} == ({'no_liver_or_heart_transplant'} if decision == 'fail' else set())


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', 'other', True, False])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'indication'}


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    result = evaluate(PACK, dict(FACTS, age_years=age))
    assert result.decision == decision
    assert {c['id'] for c in result.failed_clauses} == ({'minimum_age'} if decision == 'fail' else set())


def test_ui():
    fields = {f['key']: f for f in drug_detail('vyndaqel')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert fields['age_years']['option_style'] == 'age_bands'
    assert fields['indication']['options'] == [{'value': 'attr_cardiomyopathy', 'label': 'ATTR cardiomyopathy'}]
    assert all('when' not in c for c in PACK['criteria'])
    assert all('when' not in f for f in PACK['fact_ui'].values())
    for field in fields.values():
        assert field['type'] == 'select' and not field.get('free_text')
    for option in fields['age_years']['options']:
        patient = _coerce_patient(dict(FACTS, age_years=option['value']))
        assert evaluate(PACK, patient).decision == ('pass' if patient['age_years'] >= 18 else 'fail')


def test_metadata_and_catalog():
    assert len(PACK['criteria']) == 7
    assert PACK['drug'] == dict(name='Vyndaqel', generic_name='tafamidis meglumine', therapeutic_class='ttr-stabilizer')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2020-01-06'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/bzii2oda/201911vyndaqel_vyndamax_criteria_approved_2019.pdf'
    assert PACK['source']['criteria_pdf'] == 'data/alaska/raw/201911vyndaqel_vyndamax_criteria_approved_2019.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['Version 1', '8/13/2019', '11/15/2019', '1/6/2020', '3 months', '12 months', 'fetal harm', 'contraception', 'Breastfeeding', 'not equivalent', 'Vyndamax', 'tafamidis', '120 capsules', '80 mg per day', '30 capsules', '61 mg', 'manual review']:
        assert text in ' '.join(PACK['notes'])
    assert (BASE / 'vyndaqel.json').read_bytes() == (BASE / 'rule_packs/vyndaqel.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 106
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 92
    for slug in ['actiq', 'andembry']:
        assert catalog[slug]['encoding_status'] == 'partial'
    assert catalog['lemtrada']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert status['encoding_partial'] == 106 and status['encoding_text_only'] == 92
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'myqorzotm'
