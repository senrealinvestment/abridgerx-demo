"""Archived Zydelig indication branches and renewal toxicity boundaries."""
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
PACK = json.loads((BASE / 'rule_packs/zydelig.json').read_text())
INDS = ['relapsed_cll', 'relapsed_follicular_b_cell_nhl', 'relapsed_sll']
FACTS = dict(indication=INDS[0], concomitant_rituximab=True,
             pregnant=False, authorization_type='initial')
TOX = dict(ast_uln=20, alt_uln=20, bilirubin_uln=10, life_threatening_diarrhea=False)


@pytest.mark.parametrize('indication', INDS)
@pytest.mark.parametrize('value', [None, 0, 1, 2, 3])
def test_branches(indication, value):
    facts = dict(FACTS, indication=indication)
    key = 'concomitant_rituximab' if indication == INDS[0] else 'prior_systemic_therapy_count'
    facts[key] = (None if value is None else bool(value)) if indication == INDS[0] else value
    result = evaluate(PACK, facts)
    expected = 'need_info' if value is None else 'pass' if value >= (1 if indication == INDS[0] else 2) else 'fail'
    assert result.decision == expected
    assert result.missing_facts == ([key] if value is None else [])
    assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('context', ['initial', 'renewal', 'reauthorization'])
@pytest.mark.parametrize('key,values', [('ast_uln', [None, 19.9, 20, 20.1]),
    ('alt_uln', [None, 19.9, 20, 20.1]), ('bilirubin_uln', [None, 9.9, 10, 10.1]),
    ('life_threatening_diarrhea', [None, False, True])])
def test_renewal(context, key, values):
    for value in values:
        facts = dict(FACTS, **TOX, authorization_type=context)
        facts[key] = value
        denied = value is True if key == 'life_threatening_diarrhea' else value is not None and value > TOX[key]
        expected = 'pass' if context == 'initial' else 'need_info' if value is None else 'fail' if denied else 'pass'
        result = evaluate(PACK, facts)
        assert result.decision == expected
        assert result.missing_facts == ([key] if expected == 'need_info' else [])
        if expected == 'fail':
            assert [c['id'] for c in result.failed_clauses] == [key]


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('key,value', [('indication','other'), ('indication',True),
    ('authorization_type','other'), ('pregnant',True)])
def test_closed_and_denials(key, value):
    assert evaluate(PACK, dict(FACTS, **{key:value})).decision == 'fail'


def test_gates():
    assert [c['when'] for c in PACK['criteria'][1:4]] == [dict(fact='indication',eq=i) for i in INDS]
    assert set(evaluate(PACK, {}).missing_facts) == {'indication','pregnant','authorization_type'}
    for ind in INDS[1:]:
        assert evaluate(PACK, dict(indication=ind, prior_systemic_therapy_count=2,
            pregnant=False, authorization_type='initial')).decision == 'pass'
    result = evaluate(PACK, dict(FACTS, authorization_type='renewal', pregnant=True,
        ast_uln=21, alt_uln=21, bilirubin_uln=11, life_threatening_diarrhea=True))
    assert {c['id'] for c in result.failed_clauses} == set(TOX) | {'pregnant'}


def test_ui_notes_metadata():
    detail = drug_detail('zydelig')
    assert detail['can_evaluate']
    fields = {f['key']:f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS) | set(TOX) | {'prior_systemic_therapy_count'}
    for key,field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            facts = dict(FACTS, **TOX, authorization_type='renewal', prior_systemic_therapy_count=2)
            if key == 'prior_systemic_therapy_count': facts['indication'] = INDS[1]
            facts[key] = option['value']
            deny = (key == 'pregnant' and option['value']=='yes' or
                key == 'concomitant_rituximab' and option['value']=='no' or
                key == 'prior_systemic_therapy_count' and int(option['value'])<2 or
                key == 'life_threatening_diarrhea' and option['value']=='yes' or
                key in ['ast_uln','alt_uln','bilirubin_uln'] and float(option['value'])>TOX[key])
            assert evaluate(PACK, _coerce_patient(facts)).decision == ('fail' if deny else 'pass')
    for key in TOX:
        assert fields[key]['when']['in'] == ['renewal','reauthorization']
    assert PACK['drug']['generic_name'] == 'idelalisib'
    assert PACK['drug']['therapeutic_class'] == 'pi3k-delta-inhibitor'
    assert PACK['source']['effective_date'] == '2014-11-21'
    assert PACK['encoding_status'] == 'partial' and PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    for phrase in ['1970-01-01','hepatotoxicity','colitis','pneumonitis','intestinal perforation',
        'rituximab alone','comorbidities','Overall Response Rate','survival','up to 1 year','two 150mg capsules','manual review']:
        assert phrase in ' '.join(PACK['notes'])
    assert evaluate(PACK, dict(FACTS, requested_units=9999)).decision == 'pass'


def test_catalog():
    catalog = load_rule_pack_catalog()
    assert catalog['zydelig'] == PACK
    assert (BASE/'zydelig.json').read_bytes() == (BASE/'rule_packs/zydelig.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f: assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 178
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 20
    for directory in [BASE,BASE.parent]:
        status = json.loads((directory/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'],status['encoding_text_only']) == (178,20)
        assert status['next_candidate'] == 'oral-buprenorphine-based-medication-assisted-therapy-office-based-opioid-treatme'
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status']=='partial')
    assert catalog['bone-resorption-inhibitors']['encoding_status'] == 'partial'
