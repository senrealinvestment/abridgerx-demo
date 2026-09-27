"""Gralise/Horizant indication gates, treatment alternatives, UI and artifacts."""
import gzip
import itertools
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
PACK = json.loads((BASE / 'rule_packs/gralise.json').read_text())
PHN = 'postherpetic_neuralgia'
RLS = 'restless_leg_syndrome'
PHN_FACTS = ['gabapentin_trial_8_weeks_1800_mg', 'phn_current_therapy_responding',
             'gabapentin_ingredient_contraindication_adverse_event']
RLS_FACTS = ['pramipexole_trial_4_weeks', 'ropinirole_trial_4_weeks',
             'horizant_current_therapy_responding', 'rls_ingredient_contraindication_adverse_event']


@pytest.mark.parametrize('product', ['gralise', 'horizant'])
@pytest.mark.parametrize('values', list(itertools.product([False, True], repeat=3)))
def test_phn_truth_table(product, values):
    patient = dict(indication=PHN, product=product, **dict(zip(PHN_FACTS, values)))
    assert evaluate(PACK, patient).decision == ('pass' if any(values) else 'fail')


@pytest.mark.parametrize('values', list(itertools.product([False, True], repeat=4)))
def test_rls_truth_table(values):
    patient = dict(indication=RLS, product='horizant', age_years=18, daily_dose_mg=600,
                   **dict(zip(RLS_FACTS, values)))
    expected = (values[0] and values[1]) or values[2] or values[3]
    assert evaluate(PACK, patient).decision == ('pass' if expected else 'fail')


@pytest.mark.parametrize('fact', PHN_FACTS)
def test_phn_short_circuit(fact):
    assert evaluate(PACK, dict(indication=PHN, product='gralise', **{fact: True})).decision == 'pass'


@pytest.mark.parametrize('branch', [dict(pramipexole_trial_4_weeks=True, ropinirole_trial_4_weeks=True),
    dict(horizant_current_therapy_responding=True), dict(rls_ingredient_contraindication_adverse_event=True)])
def test_rls_gates_apply_to_every_branch(branch):
    good = dict(indication=RLS, product='horizant', age_years=18, daily_dose_mg=600, **branch)
    assert evaluate(PACK, good).decision == 'pass'
    for key, value in [('product', 'gralise'), ('product', 'other'), ('indication', 'other'),
                       ('daily_dose_mg', 600.01), ('age_years', 17.99)]:
        result = evaluate(PACK, dict(good, **{key: value}))
        assert result.decision == 'fail'
        assert result.citations == [PACK['source']['citation']]
    for key in ['indication', 'product', 'age_years', 'daily_dose_mg']:
        for null in [False, True]:
            patient = good.copy()
            if null:
                patient[key] = None
            else:
                del patient[key]
            result = evaluate(PACK, patient)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]


def test_isolation_and_missing():
    assert evaluate(PACK, {}).missing_facts == ['indication']
    for indication, facts, unrelated in [(PHN, PHN_FACTS, RLS_FACTS), (RLS, RLS_FACTS, PHN_FACTS)]:
        patient = dict(indication=indication, product='horizant', age_years=18, daily_dose_mg=600,
                       **dict.fromkeys(unrelated, True))
        result = evaluate(PACK, patient)
        assert result.decision == 'need_info'
        assert set(result.missing_facts) == set(facts)
        for missing in facts:
            candidate = dict(patient, **dict.fromkeys(facts, False))
            candidate[missing] = None
            # One unknown dopamine agonist with the other false cannot satisfy the AND.
            expected = 'fail' if missing in RLS_FACTS[:2] else 'need_info'
            assert evaluate(PACK, candidate).decision == expected
    assert evaluate(PACK, dict(indication=PHN, product='other', phn_current_therapy_responding=True)).decision == 'fail'


def test_ui():
    fields = {f['key']: f for f in drug_detail('gralise')['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    assert fields['product']['when'] == {'fact': 'indication', 'in': [PHN, RLS]}
    for fact in PHN_FACTS + RLS_FACTS + ['age_years', 'daily_dose_mg']:
        expected = {'fact': 'indication', 'in': [PHN if fact in PHN_FACTS else RLS]}
        assert fields[fact]['when'] == PACK['fact_ui'][fact]['when'] == expected
    for fact, field in fields.items():
        assert field['type'] == 'select'
        assert field['option_source'] == 'fact_ui'
        for option in field['options']:
            value = _coerce_patient({fact: option['value']})[fact]
            if fact in PHN_FACTS + RLS_FACTS:
                assert isinstance(value, bool)
            if fact in ['age_years', 'daily_dose_mg']:
                assert isinstance(value, (int, float))


def test_artifacts():
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2018-01-01'
    assert 'inferred_required_facts' not in PACK
    assert PACK['max_units'] is None
    notes = ' '.join(PACK['notes'])
    for text in ['9/04/2018', '9/21/2018', '6 months', '12 months', '1800 mg/day',
                 '1200 mg/day', '30 × 300', '90 × 600', '60 × 600', 'suicidal', 'renal', 'not interchangeable']:
        assert text in notes
    assert (BASE/'gralise.json').read_bytes() == (BASE/'rule_packs/gralise.json').read_bytes()
    catalog = json.loads((BASE/'rule_packs_all.json').read_text())
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE/'rule_packs').glob('*.json')}
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 184
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 14
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (184, 14, 'h-pylori-kits')
    assert 'gralise' in status['partial_slugs']
    assert catalog['h-pylori-kits']['encoding_status'] == 'text_only'
