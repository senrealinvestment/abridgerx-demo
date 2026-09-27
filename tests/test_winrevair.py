"""Winrevair: source-specific gates, UI choices, missing facts and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/winrevair.json').read_text())
FACTS = dict(
    indication='who_group_1_pah', age_years=18,
    prescriber_specialty='cardiologist_or_pulmonologist_or_consult',
    pah_confirmed_by_right_heart_catheterization='rhc_confirmed',
    who_functional_class='ii',
    dual_pah_background_therapy_ge_60d='two_or_more_classes_each_ge_60d',
    pregnancy_attestation='not_pregnant_will_not_become_pregnant',
)


@pytest.mark.parametrize('fact,allowed,denied', [
    ('prescriber_specialty', [FACTS['prescriber_specialty']], ['none']),
    ('pah_confirmed_by_right_heart_catheterization', ['rhc_confirmed'], ['not_confirmed']),
    ('who_functional_class', ['ii', 'iii', 'iv'], ['i_or_not_documented']),
    ('dual_pah_background_therapy_ge_60d', ['two_or_more_classes_each_ge_60d'], ['not_met']),
    ('pregnancy_attestation', ['not_pregnant_will_not_become_pregnant', 'not_applicable_male'], ['pregnant_or_no_attestation']),
])
def test_clinical_gates(fact, allowed, denied):
    assert {o['value'] for o in PACK['fact_ui'][fact]['options']} == set(allowed + denied)
    for value in allowed + denied + ['unknown', 'yes', 'no']:
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


@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', 'other', 'who_group_2_pah', True, False])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'indication'}


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    result = evaluate(PACK, dict(FACTS, age_years=age))
    assert result.decision == decision
    assert {c['id'] for c in result.failed_clauses} == ({'age_years'} if decision == 'fail' else set())


def test_ui():
    fields = {f['key']: f for f in drug_detail('winrevair')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert fields['age_years']['option_style'] == 'age_bands'
    assert fields['indication']['options'] == [{'value': 'who_group_1_pah', 'label': 'WHO Group 1 PAH'}]
    assert all('when' not in c for c in PACK['criteria'])
    assert all('when' not in f for f in PACK['fact_ui'].values())
    for field in fields.values():
        assert field['type'] == 'select' and not field.get('free_text')
    for option in fields['age_years']['options']:
        patient = _coerce_patient(dict(FACTS, age_years=option['value']))
        assert evaluate(PACK, patient).decision == ('pass' if patient['age_years'] >= 18 else 'fail')


def test_metadata_and_catalog():
    assert len(PACK['criteria']) == 7
    assert PACK['drug'] == dict(name='Winrevair', generic_name='sotatercept-csrk', therapeutic_class='pulmonary-arterial-hypertension')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2025-01-01'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/dzvlzgr1/winrevair_criteria_2024.pdf'
    assert PACK['source']['criteria_pdf'] == 'data/alaska/raw/winrevair_criteria_2024.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['Version 1', '10/15/2024', '11/15/2024', '01/01/2025', '3 months', '1 year', '0.7 mg/kg', 'every 3 weeks', 'bleeding', 'prostacyclins', 'antithrombotics', 'erythrocytosis', 'thrombocytopenia', 'fertility', 'manual review']:
        assert text in ' '.join(PACK['notes'])
    assert (BASE / 'winrevair.json').read_bytes() == (BASE / 'rule_packs/winrevair.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 93
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 105
    for slug in ['actiq', 'andembry']:
        assert catalog[slug]['encoding_status'] == 'partial'
    assert catalog['lemtrada']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert status['encoding_partial'] == 93 and status['encoding_text_only'] == 105
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'ztalmy'


def test_male_exemption_does_not_bypass_other_criteria():
    result = evaluate(PACK, dict(FACTS, pregnancy_attestation='not_applicable_male',
                                 dual_pah_background_therapy_ge_60d='not_met'))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'dual_pah_background_therapy_ge_60d'}
