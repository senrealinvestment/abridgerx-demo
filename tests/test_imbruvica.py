"""Archived Alaska Imbruvica branches and renewal denial boundaries."""
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
PACK = json.loads((BASE / 'rule_packs/imbruvica.json').read_text())
INDS = ['mantle_cell_lymphoma', 'chronic_lymphocytic_leukemia',
        'chronic_lymphocytic_leukemia_17p_deletion']
FACTS = dict(indication=INDS[0], prior_therapy_count=1, pregnant=False,
             authorization_type='initial')


@pytest.mark.parametrize('indication', INDS)
@pytest.mark.parametrize('prior', [None, 0, 1, 2])
def test_branches(indication, prior):
    facts = dict(FACTS, indication=indication, prior_therapy_count=prior)
    result = evaluate(PACK, facts)
    expected = 'pass' if indication == INDS[2] or (prior is not None and prior >= 1) else 'need_info' if prior is None else 'fail'
    assert result.decision == expected
    assert result.citations
    assert result.missing_facts == (['prior_therapy_count'] if expected == 'need_info' else [])
    if expected == 'fail':
        assert [c['id'] for c in result.failed_clauses] == ['mcl_approval' if indication == INDS[0] else 'cll_without_17p_approval']


@pytest.mark.parametrize('context', ['initial', 'renewal', 'reauthorization'])
@pytest.mark.parametrize('count', [None, 0, 2, 3, 4, 5])
def test_renewal(context, count):
    result = evaluate(PACK, dict(FACTS, authorization_type=context, toxicity_therapy_interruptions=count))
    expected = 'pass' if context == 'initial' else 'need_info' if count is None else 'fail' if count > 3 else 'pass'
    assert result.decision == expected
    if expected == 'need_info':
        assert result.missing_facts == ['toxicity_therapy_interruptions']
    if expected == 'fail':
        assert [c['id'] for c in result.failed_clauses] == ['toxicity_therapy_interruptions']


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    assert evaluate(PACK, facts).missing_facts == [key]
    assert evaluate(PACK, facts).decision == 'need_info'


@pytest.mark.parametrize('key,value', [('indication', 'other'), ('indication', True),
    ('authorization_type', 'other'), ('pregnant', True)])
def test_denials(key, value):
    assert evaluate(PACK, dict(FACTS, **{key: value})).decision == 'fail'


def test_gates_and_empty():
    branches = PACK['criteria'][1:4]
    assert [c['when'] for c in branches] == [dict(fact='indication', eq=i) for i in INDS]
    assert set(evaluate(PACK, {}).missing_facts) == {'indication', 'pregnant', 'authorization_type'}
    facts = dict(FACTS, indication=INDS[2])
    del facts['prior_therapy_count']
    assert evaluate(PACK, facts).decision == 'pass'
    result = evaluate(PACK, dict(FACTS, pregnant=True, authorization_type='renewal', toxicity_therapy_interruptions=4))
    assert {c['id'] for c in result.failed_clauses} == {'pregnant', 'toxicity_therapy_interruptions'}


def test_ui_and_notes():
    detail = drug_detail('imbruvica')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS) | {'toxicity_therapy_interruptions'}
    assert [o['value'] for o in fields['indication']['options']] == INDS
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            facts = dict(FACTS, authorization_type='renewal', toxicity_therapy_interruptions=3)
            facts[key] = option['value']
            expected = 'fail' if (key, option['value']) in [('prior_therapy_count', '0'), ('pregnant', 'yes'), ('toxicity_therapy_interruptions', '4')] else 'pass'
            assert evaluate(PACK, _coerce_patient(facts)).decision == expected
    assert fields['prior_therapy_count']['when']['in'] == INDS[:2]
    assert fields['toxicity_therapy_interruptions']['when']['in'] == ['renewal', 'reauthorization']
    assert PACK['drug']['generic_name'] == 'ibrutinib'
    assert PACK['drug']['therapeutic_class'] == 'btk-inhibitor'
    assert PACK['source']['effective_date'] == '2022-05-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    notes = ' '.join(PACK['notes'])
    for phrase in ['11/14/2014', '11/21/2014', 'strong CYP3A', 'inducers', 'moderate CYP3A', 'dose reduction', 'up to 1 year', '560 mg', '420 mg', 'manual review']:
        assert phrase in notes
    assert evaluate(PACK, dict(FACTS, requested_units=9999, strong_cyp3a_inhibitor=True)).decision == 'pass'


def test_catalog():
    catalog = load_rule_pack_catalog()
    assert catalog['imbruvica'] == PACK
    assert (BASE / 'imbruvica.json').read_bytes() == (BASE / 'rule_packs/imbruvica.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 179
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 19
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (179, 19)
        assert status['next_candidate'] == 'metformin-er'
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status'] == 'partial')
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    assert catalog['interleukin-5-inhibitors']['criteria']
