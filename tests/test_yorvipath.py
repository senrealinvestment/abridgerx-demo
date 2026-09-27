"""Yorvipath source gates, independent calcium requirements and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/yorvipath.json').read_text())
FACTS = dict(
    indication='hypoparathyroidism', age_years=18,
    prescriber_specialty='endocrinologist_or_nephrologist_or_consult',
    baseline_albumin_corrected_ca_ge_7_8_on_ca_and_active_vitd='ge_7_8',
    baseline_vitamin_d_above_lln='above_lln',
    calcium_active_vitd_step_ge_12wk='inadequate_response_ge_12wk_after_vitd_restored',
    will_continue_ca_and_vitd_during_titration='will_continue',
    not_acute_postsurgical_hypoparathyroidism=True,
    albumin_adjusted_ca_not_ge_8_3_on_ca_vitd_prior='lt_8_3_eligible',
    not_pseudohypoparathyroidism=True,
)


def test_eligible():
    assert evaluate(PACK, FACTS).decision == 'pass'


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', 'other', True, False, 'pseudohypoparathyroidism', 'acute_postsurgical_hypoparathyroidism'])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (17, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


def test_ui_options_and_all_denials():
    fields = {f['key']: f for f in drug_detail('yorvipath')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert fields['indication']['options'] == [{'value': 'hypoparathyroidism', 'label': 'Hypoparathyroidism'}]
    assert all('when' not in c for c in PACK['criteria'])
    denied = {'no', '0', 'other', 'lt_7_8_or_not_documented', 'not_met', 'will_not', 'ge_8_3_or_not_documented'}
    for fact, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{fact: value})))
            assert result.decision == ('fail' if value in denied else 'pass'), (fact, value)
            assert {c['id'] for c in result.failed_clauses} == ({'minimum_age' if fact == 'age_years' else fact} if value in denied else set())
            assert result.citations


@pytest.mark.parametrize('baseline', ['ge_7_8', 'lt_7_8_or_not_documented'])
@pytest.mark.parametrize('prior', ['lt_8_3_eligible', 'ge_8_3_or_not_documented'])
def test_calcium_gates_are_independent(baseline, prior):
    result = evaluate(PACK, dict(FACTS,
        baseline_albumin_corrected_ca_ge_7_8_on_ca_and_active_vitd=baseline,
        albumin_adjusted_ca_not_ge_8_3_on_ca_vitd_prior=prior))
    failed = set()
    if baseline != 'ge_7_8':
        failed.add('baseline_albumin_corrected_ca_ge_7_8_on_ca_and_active_vitd')
    if prior != 'lt_8_3_eligible':
        failed.add('albumin_adjusted_ca_not_ge_8_3_on_ca_vitd_prior')
    assert {c['id'] for c in result.failed_clauses} == failed
    assert result.decision == ('fail' if failed else 'pass')


def test_metadata_notes_and_catalog():
    assert PACK['drug'] == dict(name='Yorvipath', generic_name='palopegteriparatide', therapeutic_class='endocrinology')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2026-06-01'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/zl5lhrqn/yorvipath_criteria_2026.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert len(PACK['criteria']) == 10
    assert 'inferred_required_facts' not in PACK
    assert {f for c in PACK['criteria'] for f in c['required_facts']} == set(FACTS)
    for phrase in ['6 months', '12 months', 'two pens per month', '30 mcg per day', '7 to 10 days', 'osteosarcoma', 'orthostatic hypotension', 'Version 1', '2/27/2026', '4/17/2026', '6/1/2026', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])
    assert (BASE / 'yorvipath.json').read_bytes() == (BASE / 'rule_packs/yorvipath.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 95
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 103
    assert catalog['epidiolex']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert status['encoding_partial'] == 95 and status['encoding_text_only'] == 103
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'firazyr'
    assert (BASE / 'ENCODING_STATUS.md').read_bytes() == (BASE.parent / 'ENCODING_STATUS.md').read_bytes()
