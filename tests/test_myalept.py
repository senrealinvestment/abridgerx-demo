"""Myalept source gates, UI coercion, exclusions, and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/myalept.json').read_text())
FACTS = dict(
    indication='congenital_generalized_lipodystrophy', age_years=18,
    prescriber_specialty='endocrinologist_or_cardiologist_or_consult',
    additional_diagnosis='diabetes_mellitus', baseline_labs_obtained=True,
    adjunct_to_diet_modification=True, physician_rems_enrolled=True,
    no_hiv_related_lipodystrophy=True, no_partial_lipodystrophy=True,
    no_liver_disease=True,
    no_general_obesity_without_congenital_leptin_deficiency=True,
)


@pytest.mark.parametrize('indication', ['congenital_generalized_lipodystrophy', 'acquired_generalized_lipodystrophy'])
@pytest.mark.parametrize('diagnosis', ['diabetes_mellitus', 'hypertriglyceridemia_ge_200', 'high_fasting_insulin_ge_30'])
def test_allowed_routes(indication, diagnosis):
    assert evaluate(PACK, dict(FACTS, indication=indication, additional_diagnosis=diagnosis)).decision == 'pass'


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('fact', ['indication', 'additional_diagnosis'])
@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', 'other', 'none', True, False, 'partial_lipodystrophy', 'hiv_related_lipodystrophy'])
def test_closed_lists(fact, value):
    result = evaluate(PACK, dict(FACTS, **{fact: value}))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {fact}


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


def test_ui_options_and_all_denials():
    fields = {f['key']: f for f in drug_detail('myalept')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert len(fields['indication']['options']) == 2
    assert [o['value'] for o in fields['additional_diagnosis']['options']] == ['diabetes_mellitus', 'hypertriglyceridemia_ge_200', 'high_fasting_insulin_ge_30', 'none']
    assert all('when' not in c for c in PACK['criteria'])
    for fact, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{fact: value})))
            denied = value in {'no', 'none', '0'}
            assert result.decision == ('fail' if denied else 'pass'), (fact, value)
            assert {c['id'] for c in result.failed_clauses} == ({'minimum_age' if fact == 'age_years' else fact} if denied else set())
            assert result.citations


def test_metadata_notes_and_catalog():
    assert PACK['drug'] == dict(name='Myalept', generic_name='metreleptin', therapeutic_class='lipotropics')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2022-01-04'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/vrtm0qt4/202111-myalept_criteria_2021.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert len(PACK['criteria']) == 11
    assert 'inferred_required_facts' not in PACK
    assert {f for c in PACK['criteria'] for f in c['required_facts']} == set(FACTS)
    for phrase in ['3 months', '6 months', 'positive clinical response', 'dietary modifications', '10 mg/day', '1 vial per day', 'neutralizing activity', 'large reductions', 'blood glucose', 'autoimmune', 'hematologic', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])
    assert (BASE / 'myalept.json').read_bytes() == (BASE / 'rule_packs/myalept.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 186
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 12
    assert catalog['epidiolex']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert status['encoding_partial'] == 186 and status['encoding_text_only'] == 12
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'insulin-pens'
    assert (BASE / 'ENCODING_STATUS.md').read_bytes() == (BASE.parent / 'ENCODING_STATUS.md').read_bytes()
