"""Alaska Rezdiffra eligibility, strict fibrosis thresholds, and catalog mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/rezdiffratm.json').read_text())
FACTS = dict(indication='noncirrhotic_nash_with_moderate_to_advanced_fibrosis',
             age='at_least_18', prescriber_specialty='gastroenterologist', fibrosis_stage='F2',
             liver_biopsy='f2_f3_within_12_months', fib4_score='at_1_3',
             metabolic_risk_factors='at_least_3', lifestyle_modification='both_documented',
             other_liver_disease='absent')
SCORES = ['mre_score', 'vcte_score', 'elf_score']


@pytest.mark.parametrize('clause', [c for c in PACK['criteria'] if c['id'] != 'fibrosis_confirmation'])
def test_closed_gates(clause):
    key = clause['id']
    for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['yes', 'no', 'unknown', True, False]:
        result = evaluate(PACK, dict(FACTS, **{key: value}))
        allowed = value in clause['predicate']['values']
        assert result.decision == ('pass' if allowed else 'fail')
        assert [c['id'] for c in result.failed_clauses] == ([] if allowed else [key])
        assert result.citations


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert key in result.missing_facts


@pytest.mark.parametrize('scores', list(product(['above_threshold', 'at_threshold', 'below_threshold', 'not_performed'], repeat=3)))
@pytest.mark.parametrize('biopsy', ['f2_f3_within_12_months', 'older_than_12_months', 'not_confirmed'])
def test_confirmation_routes(scores, biopsy):
    facts = dict(FACTS, liver_biopsy=biopsy, **dict(zip(SCORES, scores)))
    result = evaluate(PACK, facts)
    passes = biopsy == 'f2_f3_within_12_months' or scores.count('above_threshold') >= 2
    assert result.decision == ('pass' if passes else 'fail')
    assert [c['id'] for c in result.failed_clauses] == ([] if passes else ['fibrosis_confirmation'])


@pytest.mark.parametrize('missing_score', SCORES)
def test_two_scores_suffice_without_biopsy_or_third_score(missing_score):
    facts = {k:v for k,v in FACTS.items() if k != 'liver_biopsy'}
    facts.update({k:'above_threshold' for k in SCORES if k != missing_score})
    assert evaluate(PACK, facts).decision == 'pass'
    facts[next(k for k in SCORES if k != missing_score)] = 'at_threshold'
    assert evaluate(PACK, facts).decision == 'need_info'


def test_ui_metadata_and_notes():
    detail = drug_detail('rezdiffratm')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS) | set(SCORES)
    assert len(fields['indication']['options']) == 1
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert evaluate(PACK, _coerce_patient(FACTS)).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'resmetirom'
    assert PACK['drug']['therapeutic_class'] == 'thr-beta-agonist'
    assert PACK['source']['effective_date'] == '2026-06-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['decompensated cirrhosis', 'cholelithiasis', 'cholecystitis', 'hepatotoxicity',
                 'diarrhea', 'pruritus', 'nausea', 'abdominal pain', '3 months', '12 months',
                 '30 tablets per 30 days', '100 mg/day', 'manual review']:
        assert text in ' '.join(PACK['notes'])


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['rezdiffratm'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'rezdiffratm.json').read_bytes() == (BASE / 'rule_packs/rezdiffratm.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 135
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 63
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (135, 63)
        assert status['next_candidate'] == 'reyvow'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
