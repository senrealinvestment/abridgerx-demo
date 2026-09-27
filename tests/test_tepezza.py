"""Tepezza: source-specific gates, UI choices, missing facts and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/tepezza.json').read_text())
FACTS = dict(
    indication='thyroid_eye_disease', age_years=18,
    prescriber_specialty='ophthalmology_endocrinology_oculoplastic_or_neuroophth_or_consult',
    thyroid_status='euthyroid', clinical_activity_score='cas_gte_4_worse_eye',
    active_ted_daily_living_impact='non_sight_threatening_significant_impact',
    glucocorticoid_step='inadequate_response_high_dose_gc_1mo',
    pregnancy_contraception_attestation='not_pregnant_contraception_before_during_6mo_after',
    diabetes_controlled='no_poorly_uncontrolled_diabetes',
)


@pytest.mark.parametrize('fact,allowed,denied', [
    ('prescriber_specialty', [FACTS['prescriber_specialty']], ['none']),
    ('thyroid_status', ['euthyroid', 'mild_hypo_or_hyper_ft4_ft3_within_50pct_normal'], ['uncontrolled_or_not_documented']),
    ('clinical_activity_score', ['cas_gte_4_worse_eye'], ['cas_lt_4_or_not_documented']),
    ('active_ted_daily_living_impact', ['non_sight_threatening_significant_impact'], ['sight_threatening_or_not_documented']),
    ('glucocorticoid_step', ['inadequate_response_high_dose_gc_1mo', 'contraindication_or_intolerance_high_dose_gc'], ['none']),
    ('pregnancy_contraception_attestation', ['not_pregnant_contraception_before_during_6mo_after', 'not_applicable_male_or_not_of_reproductive_potential'], ['pregnant_or_no_contraception_plan']),
    ('diabetes_controlled', ['no_poorly_uncontrolled_diabetes'], ['poorly_or_uncontrolled_diabetes']),
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
    fields = {f['key']: f for f in drug_detail('tepezza')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert fields['age_years']['option_style'] == 'age_bands'
    assert fields['indication']['options'] == [{'value': 'thyroid_eye_disease', 'label': 'Thyroid Eye Disease (Graves’ disease with TED)'}]
    for field in fields.values():
        assert field['type'] == 'select' and not field.get('free_text')
    for option in fields['age_years']['options']:
        patient = _coerce_patient(dict(FACTS, age_years=option['value']))
        assert evaluate(PACK, patient).decision == ('pass' if patient['age_years'] >= 18 else 'fail')


def test_metadata_and_catalog():
    assert len(PACK['criteria']) == 9
    assert PACK['drug'] == dict(name='Tepezza', generic_name='teprotumumab-trbw', therapeutic_class='igf1r-inhibitor')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2023-01-02'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/0u2eh20f/202211-tepezza_criteria_2022.pdf'
    assert PACK['source']['criteria_pdf'] == 'data/alaska/raw/202211-tepezza_criteria_2022.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['Version 1', '09/26/2022', '11/18/22', '1/2/2023', '6 months', 'reauthorization not approved', '8 infusions', '10 mg/kg', '20 mg/kg', '7 additional', 'J3490', 'IBD', 'glucose', 'infusion reaction', 'manual review', '<50%']:
        assert text in ' '.join(PACK['notes'])
    assert (BASE / 'tepezza.json').read_bytes() == (BASE / 'rule_packs/tepezza.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 153
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 45
    for slug in ['actiq', 'andembry']:
        assert catalog[slug]['encoding_status'] == 'partial'
    assert catalog['lemtrada']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert status['encoding_partial'] == 153 and status['encoding_text_only'] == 45
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'movantik'
