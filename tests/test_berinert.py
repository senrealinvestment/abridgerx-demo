"""Berinert Alaska source criteria, closed controls, and catalog integration."""
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
INDICATION = 'hae_acute_abdominal_facial_or_laryngeal_attacks'
STEP = 'failed_or_contraindicated_androgens_and_antifibrinolytics'
BOOLS = ['hae_diagnosis_by_immunologist',
         'hae_monthly_abdominal_or_respiratory_attacks_requiring_er_prior_6mo',
         'not_concurrent_ace_inhibitor_or_estrogen_replacement']


def pack():
    return json.loads((BASE / 'rule_packs/berinert.json').read_text())


def facts():
    return {'indication': INDICATION, **dict.fromkeys(BOOLS, True),
            STEP: 'insufficient_response_or_contraindication_to_both_classes'}


def test_pass_and_missing():
    assert evaluate(pack(), facts()).decision == 'pass'
    for key in facts():
        patient = facts()
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
    result = evaluate(pack(), {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(facts())


@pytest.mark.parametrize('fact,value', [
    *[(key, False) for key in BOOLS],
    *[('indication', value) for value in ['hae_prophylaxis', 'hae_acute_attacks', 'hae', 'yes', True, False]],
    *[(STEP, value) for value in ['not_met', 'androgens_only', 'antifibrinolytics_only', 'yes', True]],
])
def test_failures(fact, value):
    patient = facts()
    patient[fact] = value
    result = evaluate(pack(), patient)
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [
        'indication_fda_labeled' if fact == 'indication' else fact]


def test_ui_and_coercion():
    detail = drug_detail('berinert')
    assert detail['can_evaluate'] and detail['criteria_text']['extracted_text']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        assert field['option_source'] == 'fact_ui'
        assert field['options'] == pack()['fact_ui'][key]['options']
    assert fields['indication']['options'] == [dict(value=INDICATION, label='Acute abdominal, facial, or laryngeal HAE attacks')]
    assert [o['value'] for o in fields[STEP]['options']] == [facts()[STEP], 'not_met']
    patient = {key: field['options'][0]['value'] for key, field in fields.items()}
    assert evaluate(pack(), _coerce_patient(patient)).decision == 'pass'
    for key in BOOLS:
        assert fields[key]['options'] == [dict(value='yes', label='Yes'), dict(value='no', label='No')]
        assert evaluate(pack(), _coerce_patient(dict(patient, **{key: 'no'}))).decision == 'fail'


def test_source_and_notes():
    p = pack()
    assert p['drug'] == dict(name='Berinert', generic_name='C1 esterase inhibitor (human)', therapeutic_class='hae-treatments')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2022-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/2icfelak/berinert-pa.pdf'
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 5
    assert {c['predicate']['fact'] for c in p['criteria']} == set(facts())
    for c in p['criteria']:
        fact = c['predicate']['fact']
        assert c['required_facts'] == [fact]
        assert c['predicate'] == ({'op': 'in', 'fact': fact, 'values': [INDICATION]} if fact == 'indication' else {'op': 'eq', 'fact': fact, 'value': facts()[fact]})
    notes = ' '.join(p['notes'])
    for term in ['Version 1', '1/7/2013', '01/18/2013', 'letter of medical necessity',
                 'ER documentation', 'endocrinologist', 'Both preventative medication classes',
                 'prophylactic therapy have not been established', 'adults and adolescents']:
        assert term in notes
    assert p['alternatives'] == ['cinryze', 'ekterly']


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['berinert'] == pack()
    assert (BASE / 'berinert.json').read_bytes() == (BASE / 'rule_packs/berinert.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 89
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 109
    assert catalog['cinryze']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (89, 109)
    assert status['next_candidate'] == 'epidiolex'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
