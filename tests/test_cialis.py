"""Cialis BPH criteria, missing facts, UI gating and archived source metadata."""
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
PACK = json.loads((BASE / 'rule_packs/cialis.json').read_text())
INDICATION = 'benign_prostatic_hyperplasia'
GATES = ['no_current_alpha_blocker_or_nitrate', 'failed_alpha_blocker_30d_or_5ari_6mo']
FACTS = dict(indication=INDICATION, patient_male=True, **dict.fromkeys(GATES, True))


@pytest.mark.parametrize('male', [{'patient_male': True}, {'sex': 'male'}, {'sex': None, 'patient_male': True}, {'sex': 'male', 'patient_male': True}])
def test_approval(male):
    facts = {k: v for k, v in FACTS.items() if k != 'patient_male'}
    result = evaluate(PACK, dict(facts, **male))
    assert result.decision == 'pass'
    assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('male', [{'patient_male': False}, {'sex': 'female'}, {'sex': 'other'}, {'sex': 'male', 'patient_male': False}, {'sex': 'female', 'patient_male': True}])
def test_not_male(male):
    facts = {k: v for k, v in FACTS.items() if k != 'patient_male'}
    assert evaluate(PACK, dict(facts, **male)).decision == 'fail'


@pytest.mark.parametrize('key', GATES)
def test_required_gate(key):
    result = evaluate(PACK, dict(FACTS, **{key: False}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]
    assert result.failed_clauses[0]['citation'] == PACK['source']['citation']


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    expected = ['patient_male', 'sex'] if key == 'patient_male' else [key]
    assert sorted(result.missing_facts) == sorted(expected)


@pytest.mark.parametrize('indication', ['erectile_dysfunction', 'pulmonary_arterial_hypertension', 'other', '', True, False])
def test_closed_indication(indication):
    result = evaluate(PACK, {'indication': indication})
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


def test_indication_first_and_ui():
    assert evaluate(PACK, {}).missing_facts == ['indication']
    detail = drug_detail('cialis')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(FACTS) | {'sex'}
    for key in (set(FACTS) | {'sex'}) - {'indication'}:
        assert PACK['fact_ui'][key]['when'] == {'fact': 'indication', 'in': [INDICATION]}
    for male in [{'patient_male': 'yes'}, {'sex': 'male'}]:
        facts = dict(indication=INDICATION, **dict.fromkeys(GATES, 'yes'), **male)
        assert evaluate(PACK, _coerce_patient(facts)).decision == 'pass'


def test_source_and_notes():
    source = json.loads((BASE / 'criteria_text/cialis.json').read_text())
    assert source['effective_date'] is None
    assert PACK['source']['effective_date'] == '1970-01-01'
    assert PACK['source']['citation'] == source['source_url']
    assert PACK['drug']['generic_name'] == 'tadalafil'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for value in ['5 mg only', '2.5 mg, 10 mg, 20 mg', '6 months', 'new prior authorization', '30-day supply', '5 mg/day', 'Version 1', '11/18/2011']:
        assert value in notes
    step = PACK['criteria'][-1]['text']
    assert '30 days' in step and 'six months' in step and ' OR ' in step


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['cialis'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'cialis.json').read_bytes() == (BASE / 'rule_packs/cialis.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 187
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 11
    assert catalog['cialis']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (187, 11)
        assert status['next_candidate'] == 'genotypes'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
