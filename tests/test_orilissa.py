"""Alaska's single Orilissa/Oriahnn/Myfembree pack: product boundaries."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _when_applies
from ui.loaders import drug_detail, load_rule_pack_catalog
from ui.app import _coerce_patient

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/orilissa.json').read_text())
PATHS = [('orilissa', 'endometriosis_severe_pain'),
         ('oriahnn', 'fibroids_heavy_menstrual_bleeding'),
         ('myfembree', 'fibroids_heavy_menstrual_bleeding'),
         ('myfembree', 'endometriosis_moderate_to_severe_pain')]


def facts_for(product, indication):
    facts = dict(product=product, indication=indication, age_years=18)
    for clause in PACK['criteria']:
        pred = clause['predicate']
        if _when_applies(clause.get('when'), facts) and pred.get('fact') not in facts and pred['op'] == 'in':
            facts[pred['fact']] = pred['values'][0]
    return facts


@pytest.mark.parametrize('product,indication', PATHS)
def test_paths_required_facts_and_closed_values(product, indication):
    facts = facts_for(product, indication)
    assert evaluate(PACK, facts).decision == 'pass'
    for key in facts:
        for omitted in [False, True]:
            missing = dict(facts, **{key: None})
            if omitted:
                del missing[key]
            result = evaluate(PACK, missing)
            assert result.decision == 'need_info'
            assert key in result.missing_facts
    for clause in PACK['criteria']:
        pred = clause['predicate']
        if not _when_applies(clause.get('when'), facts) or pred['op'] != 'in':
            continue
        key = pred['fact']
        if key == 'product':
            continue
        for value in pred['values']:
            assert evaluate(PACK, dict(facts, **{key: value})).decision == 'pass'
        for value in ['not_met', 'other', 'contraindicated', 'intolerant', True, False]:
            result = evaluate(PACK, dict(facts, **{key: value}))
            assert result.decision == 'fail', (key, value, result)
            assert clause['id'] in [c['id'] for c in result.failed_clauses]
            assert clause['citation'] in result.citations


@pytest.mark.parametrize('product,indication', PATHS)
@pytest.mark.parametrize('age', [17, 17.99, 18, 49, 49.01, 50, 80])
def test_age_boundaries(product, indication, age):
    facts = dict(facts_for(product, indication), age_years=age)
    expected = age >= 18 and (product != 'orilissa' or age <= 49)
    assert evaluate(PACK, facts).decision == ('pass' if expected else 'fail')


@pytest.mark.parametrize('product,indication', PATHS)
def test_other_product_facts_do_not_leak(product, indication):
    facts = facts_for(product, indication)
    for key in PACK['fact_ui']:
        if key not in facts:
            facts[key] = 'not_met'
    assert evaluate(PACK, facts).decision == 'pass'
    assert evaluate(PACK, _coerce_patient(dict(facts, age_years='18'))).decision == 'pass'
    for invalid in ['unknown', 'Orilissa', True]:
        assert evaluate(PACK, dict(facts, product=invalid)).decision == 'fail'
    for other in {i for _, i in PATHS} - {indication}:
        allowed = product == 'myfembree' and other in ['fibroids_heavy_menstrual_bleeding', 'endometriosis_moderate_to_severe_pain']
        assert evaluate(PACK, dict(facts, indication=other)).decision == ('pass' if allowed else 'fail')


def test_ui_metadata_catalog_and_mirrors():
    fields = {f['key']: f for f in drug_detail('orilissa')['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    for clause in PACK['criteria']:
        key = clause['required_facts'][0]
        if key not in ['age_years', 'indication']:
            assert fields[key].get('when') == clause.get('when')
    assert PACK['drug']['therapeutic_class'] == 'gnrh-receptor-antagonist'
    assert PACK['source']['effective_date'] == '2022-11-01'
    assert PACK['encoding_status'] == 'partial' and PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for phrase in ['bone loss', 'recognize pregnancy', 'mood disorders', 'LFTs', 'estrogen-containing',
                   '6 months', '150mg dose only', '24 months', '56 capsules', '30 capsules per 30 days', 'manual review']:
        assert phrase in notes
    catalog = load_rule_pack_catalog()
    assert catalog['orilissa'] == PACK
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    assert 'oriahnn' not in catalog and 'myfembree' not in catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 140
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 58
    assert (BASE / 'orilissa.json').read_bytes() == (BASE / 'rule_packs/orilissa.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (140, 58)
    assert status['next_candidate'] == 'vesicular-monoamine'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
