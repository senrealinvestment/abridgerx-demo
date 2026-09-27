"""Tolvaptan product gates, sodium alternatives, shared denials and catalog parity."""
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
A = 'adpkd_kidney_function_decline'
S = 'hypervolemic_or_euvolemic_hyponatremia'


def pack():
    return json.loads((BASE / 'rule_packs/jynarque.json').read_text())


def patient(indication):
    facts = {'indication': indication}
    for c in pack()['criteria'][1:]:
        if c.get('when', {}).get('in', [indication]) != [indication]:
            continue
        p = c['predicate']
        if p['op'] == 'any':
            facts.update(serum_sodium_meq_l=124)
        else:
            facts[p['fact']] = p['values'][0] if p['op'] == 'in' else p['value']
    return facts


@pytest.mark.parametrize('indication', [A, S])
def test_requirements_and_branch_isolation(indication):
    p = pack()
    baseline = patient(indication)
    assert evaluate(p, baseline).decision == 'pass'
    for fact in baseline:
        for value in ['missing', None]:
            facts = baseline.copy()
            if value == 'missing':
                del facts[fact]
            else:
                facts[fact] = value
            result = evaluate(p, facts)
            assert result.decision == 'need_info'
            assert fact in result.missing_facts
    for c in p['criteria']:
        if c.get('when', {}).get('in', [indication]) != [indication]:
            facts = dict(baseline, **dict.fromkeys(c['required_facts'], False))
            assert evaluate(p, facts).decision == 'pass'
        elif c['predicate']['op'] == 'eq':
            result = evaluate(p, dict(baseline, **{c['predicate']['fact']: False}))
            assert result.decision == 'fail'
            assert [x['id'] for x in result.failed_clauses] == [c['id']]
    for invalid in ['other', 'adpkd', 'hyponatremia', True, False]:
        assert evaluate(p, dict(baseline, indication=invalid)).decision == 'fail'


@pytest.mark.parametrize('sodium,symptoms,expected', [
    (124.99, None, 'pass'), (124, False, 'pass'),
    (125, True, 'pass'), (126, True, 'pass'),
    (125, False, 'fail'), (126, False, 'fail'),
    (125, None, 'need_info'), (None, True, 'need_info'),
])
def test_sodium_alternatives(sodium, symptoms, expected):
    facts = dict(patient(S), serum_sodium_meq_l=sodium,
                 symptomatic_hyponatremia_resistant_to_fluid_restriction=symptoms)
    assert evaluate(pack(), facts).decision == expected


@pytest.mark.parametrize('indication,fact,value,expected', [
    (A, 'age_years', 17.99, 'fail'), (A, 'age_years', 18, 'pass'),
    (S, 'age_years', 10, 'pass'),
    (S, 'requested_duration_days', 30, 'pass'),
    (S, 'requested_duration_days', 30.01, 'fail'),
    (A, 'requested_duration_days', 91, 'pass'),
])
def test_numeric_boundaries(indication, fact, value, expected):
    assert evaluate(pack(), dict(patient(indication), **{fact: value})).decision == expected


@pytest.mark.parametrize('indication', [A, S])
def test_specialists_and_ui(indication):
    p = pack()
    fields = {f['key']: f for f in drug_detail('jynarque')['fact_fields']}
    for c in p['criteria']:
        for fact in c['required_facts']:
            assert fields[fact].get('when') == c.get('when')
        if c['predicate']['op'] == 'in' and c['id'] != 'indication' and c['when']['in'] == [indication]:
            for option in fields[c['id']]['options']:
                result = evaluate(p, _coerce_patient(dict(patient(indication), **{c['id']: option['value']})))
                assert result.decision == ('pass' if option['value'] in c['predicate']['values'] else 'fail')
    raw = {f: next(o['value'] for o in fields[f]['options'] if o['value'] != 'other') for f in patient(indication)}
    if indication == S:
        raw['indication'] = S
    else:
        raw['age_years'] = '18'
    assert evaluate(p, _coerce_patient(raw)).decision == 'pass'
    shared = {c['id'] for c in p['criteria'] if 'when' not in c}
    assert set(evaluate(p, {}).missing_facts) == shared


def test_catalog_and_metadata():
    p = pack()
    assert p['drug']['generic_name'] == 'tolvaptan'
    assert p['source']['effective_date'] == '2022-06-01'
    assert p['encoding_status'] == 'partial'
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert (BASE / 'jynarque.json').read_bytes() == (BASE / 'rule_packs/jynarque.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['jynarque'] == p
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 113
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 85
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (113, 85)
    assert status['next_candidate'] == 'wakix'
    assert catalog['opsumit']['encoding_status'] == 'partial'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
    notes = ' '.join(p['notes'])
    for term in ['90 days', '12 months', '56 tablets per 28 days', '60 tablets per 30 days', 'moderate CYP3A inducer', 'hypernatremia', 'manual review']:
        assert term in notes
