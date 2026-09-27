"""Scopolamine approval paths, age boundary, gated facts and catalog artifacts."""
import gzip
import json
import sys
from itertools import product
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/transderm-scop.json').read_text())
A = 'post_anesthesia_surgery_nausea_vomiting'
B = 'excess_secretions'
C = 'motion_sickness_nausea_vomiting'
PRIOR = 'prior_different_drug_suboptimal_or_inappropriate'
MECLIZINE = 'failed_meclizine'


@pytest.mark.parametrize('indication,age,prior,meclizine', list(product([A, B, C], [17, 18, 65], [False, True], [False, True])))
def test_approval_truth_table(indication, age, prior, meclizine):
    result = evaluate(PACK, dict(indication=indication, age_years=age, **{PRIOR: prior, MECLIZINE: meclizine}))
    approved = age >= 18 and (indication == A or indication == B and prior or indication == C and meclizine)
    assert result.decision == ('pass' if approved else 'fail')
    assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('indication,key', [(B, PRIOR), (C, MECLIZINE)])
@pytest.mark.parametrize('value', [None, False, True])
def test_active_step(indication, key, value):
    facts = dict(indication=indication, age_years=18)
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info' and result.missing_facts == [key]
    result = evaluate(PACK, dict(facts, **{key: value}))
    assert result.decision == ('need_info' if value is None else 'pass' if value else 'fail')
    if value is False:
        assert [c['id'] for c in result.failed_clauses] == [key]
        assert result.failed_clauses[0]['citation'] == PACK['source']['citation']


@pytest.mark.parametrize('indication,key', [(A, None), (B, PRIOR), (C, MECLIZINE)])
def test_inactive_steps_not_required(indication, key):
    facts = dict(indication=indication, age_years=18)
    if key:
        facts[key] = True
    assert evaluate(PACK, facts).decision == 'pass'
    facts.pop('age_years')
    assert evaluate(PACK, facts).missing_facts == ['age_years']
    facts['age_years'] = None
    assert evaluate(PACK, facts).decision == 'need_info'


@pytest.mark.parametrize('indication', ['other', '', 'nausea_vomiting', True, False])
def test_closed_indication(indication):
    result = evaluate(PACK, dict(indication=indication, age_years=18, **{PRIOR: True, MECLIZINE: True}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


def test_missing_indication():
    assert set(evaluate(PACK, {}).missing_facts) == {'indication', 'age_years'}
    assert evaluate(PACK, {'age_years': 18, 'indication': None}).missing_facts == ['indication']


def test_ui_and_source_notes():
    detail = drug_detail('transderm-scop')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == {'indication', 'age_years', PRIOR, MECLIZINE}
    assert [o['value'] for o in fields['indication']['options']] == [A, B, C]
    for clause in PACK['criteria'][2:]:
        assert clause['when'] == PACK['fact_ui'][clause['id']]['when']
    for indication, key in [(B, PRIOR), (C, MECLIZINE)]:
        assert PACK['fact_ui'][key]['when'] == {'fact': 'indication', 'eq': indication}
        assert evaluate(PACK, _coerce_patient(dict(indication=indication, age_years='18', **{key: 'yes'}))).decision == 'pass'
    assert len(PACK['criteria']) == 4
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for text in ['1.5 mg', '1 year', '30-day supply', 'NA', 'OCR', 'Version 1', '05/28/09', '2019-11-20']:
        assert text in notes
    source = json.loads((BASE / 'criteria_text/transderm-scop.json').read_text())
    assert PACK['source']['effective_date'] == source['effective_date'] == '2019-11-20'
    assert PACK['source']['citation'] == source['source_url']


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['transderm-scop'] == PACK
    assert PACK['encoding_status'] == 'partial'
    assert catalog['dilaudid']['encoding_status'] == 'text_only'
    assert (BASE / 'transderm-scop.json').read_bytes() == (BASE / 'rule_packs/transderm-scop.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 170
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 28
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (170, 28)
        assert status['next_candidate'] == 'dilaudid'
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
