"""Palynziq: source-specific gates, UI choices, missing facts and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/palynziq.json').read_text())
FACTS = dict(
    indication='phenylketonuria', age_years=18,
    prescriber_specialty='metabolic_specialist_or_consult',
    rems_enrollment='prescriber_and_patient_enrolled',
    baseline_phenylalanine_documented='documented',
    phenylalanine_restricted_diet_active='actively_on_diet',
    uncontrolled_phe_gt_600_on_existing_mgmt='phe_gt_600_umol_l_on_existing_incl_kuvan',
    phenylalanine_monitored_through_therapy='monitored_and_recorded',
    epinephrine_autoinjector_prescribed_and_trained='prescribed_and_trained',
    not_concomitant_kuvan='not_using_kuvan_with_palynziq',
)



@pytest.mark.parametrize('fact,allowed,denied', [
    ('prescriber_specialty', [FACTS['prescriber_specialty']], ['none']),
    ('rems_enrollment', [FACTS['rems_enrollment']], ['not_enrolled']),
    ('baseline_phenylalanine_documented', ['documented'], ['not_documented']),
    ('phenylalanine_restricted_diet_active', ['actively_on_diet'], ['not_on_diet']),
    ('uncontrolled_phe_gt_600_on_existing_mgmt', [FACTS['uncontrolled_phe_gt_600_on_existing_mgmt']], ['not_met']),
    ('phenylalanine_monitored_through_therapy', ['monitored_and_recorded'], ['not_monitored']),
    ('epinephrine_autoinjector_prescribed_and_trained', ['prescribed_and_trained'], ['not_met']),
    ('not_concomitant_kuvan', ['not_using_kuvan_with_palynziq'], ['concomitant_kuvan']),
])
def test_clinical_gates(fact, allowed, denied):
    assert {o['value'] for o in PACK['fact_ui'][fact]['options']} == set(allowed + denied)
    for value in allowed + denied:
        result = evaluate(PACK, dict(FACTS, **{fact: value}))
        assert result.decision == ('pass' if value in allowed else 'fail')
        assert {c['id'] for c in result.failed_clauses} == (set() if value in allowed else {fact})
        assert result.citations


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
    fields = {f['key']: f for f in drug_detail('palynziq')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert fields['age_years']['option_style'] == 'age_bands'
    assert fields['indication']['options'] == [{'value': 'phenylketonuria', 'label': 'Confirmed phenylketonuria (PKU)'}]
    assert all('when' not in c for c in PACK['criteria'])
    assert all('when' not in f for f in PACK['fact_ui'].values())
    for field in fields.values():
        assert field['type'] == 'select' and not field.get('free_text')
    for option in fields['age_years']['options']:
        patient = _coerce_patient(dict(FACTS, age_years=option['value']))
        assert evaluate(PACK, patient).decision == ('pass' if patient['age_years'] >= 18 else 'fail')


def test_metadata_and_catalog():
    assert len(PACK['criteria']) == 10
    assert PACK['drug'] == dict(name='Palynziq', generic_name='pegvaliase-pqpz', therapeutic_class='metabolic-enzyme')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2019-03-11'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/5djjpvhf/20195-b-iii-palynziq_criteria_approved_2018.pdf'
    assert PACK['source']['criteria_pdf'] == 'data/alaska/raw/20195-b-iii-palynziq_criteria_approved_2018.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['Version 1', '12/7/2018', '1/18/19', '3/11/19', '3 months', '6 months', '≥20%', 'Phe <600', 'no toxicities', '40 mg/day', '2 syringes', '60 syringes/month', '60 minutes', 'every 4 weeks', 'Carry', 'competency', 'Black Box', 'manual review']:
        assert text in ' '.join(PACK['notes'])
    assert (BASE / 'palynziq.json').read_bytes() == (BASE / 'rule_packs/palynziq.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 157
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 41
    for slug in ['actiq', 'andembry']:
        assert catalog[slug]['encoding_status'] == 'partial'
    assert catalog['lemtrada']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert status['encoding_partial'] == 157 and status['encoding_text_only'] == 41
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'panretin'
