"""Krystexxa source gates, independent therapy steps, and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/krystexxa.json').read_text())
FACTS = dict(indication='chronic_gout_refractory', age_years=18,
    prescriber_specialty='rheumatologist_or_nephrologist_or_consult',
    chronic_gout_definition='three_or_more_flares_18mo', baseline_sua='ge_6_mg_dl',
    g6pd_screened=True, allopurinol_step='failure_after_ge_3_months',
    febuxostat_step='failure_after_ge_3_months', flare_prophylaxis='nsaid_within_30d')


def test_eligible():
    assert evaluate(PACK, FACTS).decision == 'pass'


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', 'other', True, False, 'gout', 'asymptomatic_hyperuricemia'])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (17, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


def test_ui_options_and_denials():
    fields = {f['key']: f for f in drug_detail('krystexxa')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert fields['indication']['options'] == [{'value': 'chronic_gout_refractory', 'label': 'Chronic gout refractory to conventional therapy'}]
    assert all('when' not in c for c in PACK['criteria'])
    denied = {'no', '0', 'none', 'not_met', 'lt_6_mg_dl'}
    for fact, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{fact: value})))
            assert result.decision == ('fail' if value in denied else 'pass'), (fact, value)
            assert {c['id'] for c in result.failed_clauses} == ({'minimum_age' if fact == 'age_years' else fact} if value in denied else set())
            assert result.citations


@pytest.mark.parametrize('allo', ['failure_after_ge_3_months', 'contraindication', 'intolerance', 'not_met', 'failure_after_2_months'])
@pytest.mark.parametrize('feb', ['failure_after_ge_3_months', 'contraindication', 'intolerance', 'not_met', 'failure_after_2_months'])
def test_both_steps_independently_required(allo, feb):
    result = evaluate(PACK, dict(FACTS, allopurinol_step=allo, febuxostat_step=feb))
    accepted = {'failure_after_ge_3_months', 'contraindication', 'intolerance'}
    failed = {k for k, v in [('allopurinol_step', allo), ('febuxostat_step', feb)] if v not in accepted}
    assert {c['id'] for c in result.failed_clauses} == failed
    assert result.decision == ('fail' if failed else 'pass')


@pytest.mark.parametrize('value', ['nsaid_31_days_ago', 'colchicine_31_days_ago', 'planned', 'none', 'yes'])
def test_prophylaxis_must_be_current_or_contraindicated(value):
    result = evaluate(PACK, dict(FACTS, flare_prophylaxis=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['flare_prophylaxis']


def test_metadata_notes_and_catalog():
    assert PACK['drug'] == dict(name='Krystexxa', generic_name='pegloticase', therapeutic_class='uricase')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2022-06-01'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/1scmdpo2/20220415-krystexxa_criteria_2022.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert len(PACK['criteria']) == 9
    assert 'inferred_required_facts' not in PACK
    assert {f for c in PACK['criteria'] for f in c['required_facts']} == set(FACTS)
    for phrase in ['anaphylaxis', 'pre-medicated', 'G6PD', '6 months', 'heart failure', '3 months', '12 months', 'positive clinical response', '8 mg', '16 mg', 'J2507', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])
    assert (BASE / 'krystexxa.json').read_bytes() == (BASE / 'rule_packs/krystexxa.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 142
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 56
    assert catalog['epidiolex']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert status['encoding_partial'] == 142 and status['encoding_text_only'] == 56
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'noxafil'
    assert (BASE / 'ENCODING_STATUS.md').read_bytes() == (BASE.parent / 'ENCODING_STATUS.md').read_bytes()
