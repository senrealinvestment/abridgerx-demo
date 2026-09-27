"""Vyjuvek Alaska Medicaid Version 1 eligibility and catalog regressions."""
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
GATED = {
    'col7a1_mutation_genetic_testing_confirmed',
    'baseline_target_wound_size_documented',
    'treated_wounds_meet_readiness_criteria',
}


def pack():
    return json.loads((BASE / 'rule_packs/vyjuvek.json').read_text())


def facts(**updates):
    return dict(dict(
        indication='dystrophic_epidermolysis_bullosa', age_years=0.5,
        prescriber_specialty='dermatologist',
        col7a1_mutation_genetic_testing_confirmed=True,
        baseline_target_wound_size_documented=True,
        treated_wounds_meet_readiness_criteria=True), **updates)


def assert_failure(clause, **updates):
    result = evaluate(pack(), facts(**updates))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {clause}
    assert result.citations == [pack()['source']['citation']]


def test_closed_indication_age_and_specialty():
    for specialty in ['dermatologist', 'dermatologist_consult']:
        for age in [0.5, 0.51, 3, 18, 80]:
            assert evaluate(pack(), facts(age_years=age, prescriber_specialty=specialty)).decision == 'pass'
    for value in ['yes', 'no', 'unknown', True, False, 'hemophilia_b_moderate_severe', 'hemophilia_a', 'other']:
        assert_failure('indication_fda_labeled', indication=value)
    for age in [0, 0.49, 0.4999]:
        assert_failure('age_fda_labeled', age_years=age)
    assert_failure('prescriber_specialty', prescriber_specialty='other')


@pytest.mark.parametrize('fact', [f for f, value in facts().items() if value is True])
def test_approval_attestations(fact):
    # The sole denial is failure to meet approval criteria.
    assert_failure(fact, **{fact: False})


@pytest.mark.parametrize('fact', facts())
@pytest.mark.parametrize('missing', [None, 'absent'])
def test_missing_needs_information(fact, missing):
    patient = facts()
    if missing == 'absent':
        del patient[fact]
    else:
        patient[fact] = None
    result = evaluate(pack(), patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


def test_when_gating_and_ui_options():
    fields = {f['key']: f for f in drug_detail('vyjuvek')['fact_fields']}
    assert set(fields) == set(facts())
    gate = {'fact': 'indication', 'in': ['dystrophic_epidermolysis_bullosa']}
    assert {c['required_facts'][0] for c in pack()['criteria'] if c.get('when') == gate} == GATED
    for f in GATED:
        assert fields[f]['when'] == gate
    for indication in ['other', None]:
        patient = {k: v for k, v in facts(indication=indication).items() if k not in GATED}
        result = evaluate(pack(), patient)
        assert result.decision == ('fail' if indication else 'need_info')
        assert not GATED.intersection(result.missing_facts)
    assert [o['value'] for o in fields['indication']['options']] == ['dystrophic_epidermolysis_bullosa']
    raw = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
    for fact, field in fields.items():
        assert field['type'] == 'select'
        for option in field['options']:
            value = option['value']
            good = value == raw[fact] or (fact == 'prescriber_specialty' and value == 'dermatologist_consult')
            result = evaluate(pack(), _coerce_patient(dict(raw, **{fact: value})))
            assert result.decision == ('pass' if good else 'fail'), (fact, value)


def test_metadata_notes_catalog_and_mirrors():
    p = pack()
    assert p['drug'] == dict(name='Vyjuvek', generic_name='beremagene geperpavec-svdt', therapeutic_class='cell-and-gene-therapy')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2024-01-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/c1uhnqmi/vyjuvek_criteria_2023.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/vyjuvek_criteria_2023.pdf'
    assert p['alternatives'] == [] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 6
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '10/20/2023', '11/17/2023', '01/1/2024',
                 '6 months', 'reauthorization approval up to 6 months',
                 '3.2 mL per 28 days', '6.4 mL per 28 days', 'J3401',
                 'granulation', 'vascularized', 'active infection',
                 'squamous cell carcinoma', 'pregnancy', 'lactation',
                 '24 hours', 'manual review']:
        assert text in ' '.join(p['notes'])
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 82
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 116
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'vyjuvek.json').read_bytes() == (BASE / 'rule_packs/vyjuvek.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (82, 116)
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'yorvipath'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


@pytest.mark.parametrize('value', ['0.4999', '0.5', '0.5001'])
def test_numeric_age_form_input(value):
    patient = _coerce_patient(dict(facts(), age_years=value))
    assert patient['age_years'] == float(value)
    assert evaluate(pack(), patient).decision == ('pass' if float(value) >= 0.5 else 'fail')


@pytest.mark.parametrize('value', ['', None, 'invalid'])
def test_invalid_age_form_input_needs_information(value):
    result = evaluate(pack(), _coerce_patient(dict(facts(), age_years=value)))
    assert result.decision == 'need_info'
    assert result.missing_facts == ['age_years']
