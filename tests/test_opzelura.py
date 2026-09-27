"""Opzelura indication paths, literal source boundaries and catalog mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/opzelura.json').read_text())
PATHS = {'ad': 'mild_to_moderate_atopic_dermatitis', 'vitiligo': 'nonsegmental_vitiligo'}


def facts_for(path, age=18):
    facts = dict(indication=PATHS[path], age_years=age,
                 prescriber_specialty='dermatologist_or_consult', immunocompromised='absent',
                 concurrent_biologic_or_jak='absent', concurrent_immunosuppressant='absent')
    facts[path + '_bsa'] = 'up_to_20_percent' if path == 'ad' else '10_percent'
    facts[path + '_calcineurin_step'] = 'trial_failure'
    if path == 'ad':
        facts['ad_pde4_step'] = 'trial_failure'
    if age <= 17:
        facts[path + '_low_mid_potency_corticosteroid_step'] = 'trial_failure'
    if age >= 17:
        facts[path + '_high_potency_corticosteroid_step'] = 'trial_failure'
    return facts


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('age', [11, 11.99, 12, 16, 17, 17.01, 18, 65])
def test_ages_and_missing(path, age):
    facts = facts_for(path, age)
    assert evaluate(PACK, facts).decision == ('pass' if age >= 12 else 'fail')
    if age < 12:
        return
    for key in facts:
        for value in [None, 'omit']:
            missing = dict(facts, **{key: value})
            if value == 'omit':
                del missing[key]
            result = evaluate(PACK, missing)
            assert result.decision == 'need_info', (key, result)
            assert key in result.missing_facts


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('age', [12, 17, 18])
def test_all_required_classes_independent_and_ci(path, age):
    facts = facts_for(path, age)
    for key in facts:
        if not key.endswith('_step'):
            continue
        assert evaluate(PACK, dict(facts, **{key: 'contraindicated'})).decision == 'pass'
        for bad in ['not_met', 'yes', True, 'intolerant']:
            result = evaluate(PACK, dict(facts, **{key: bad}))
            assert result.decision == 'fail'
            assert [c['id'] for c in result.failed_clauses] == [key]
    # A non-applicable potency class cannot block an otherwise qualified patient.
    if age != 17:
        potency = 'high' if age < 17 else 'low_mid'
        assert evaluate(PACK, dict(facts, **{f'{path}_{potency}_potency_corticosteroid_step': 'not_met'})).decision == 'pass'


@pytest.mark.parametrize('path', PATHS)
def test_closed_gates_and_denials(path):
    facts = facts_for(path)
    for key in ['indication', 'prescriber_specialty', path + '_bsa', 'immunocompromised',
                'concurrent_biologic_or_jak', 'concurrent_immunosuppressant']:
        clause = next(c for c in PACK['criteria'] if c['id'] == key)
        for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['other', 'yes', True, False]:
            result = evaluate(PACK, dict(facts, **{key: value}))
            if key == 'indication' and value in PATHS.values() and value != facts[key]:
                assert result.decision == 'need_info'
                continue
            allowed = value in clause['predicate']['values']
            assert result.decision == ('pass' if allowed else 'fail')
            assert clause['citation'] in result.citations


def test_indication_gates_and_ui():
    fields = {f['key']: f for f in drug_detail('opzelura')['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    for path in PATHS:
        facts = facts_for(path)
        other = 'vitiligo' if path == 'ad' else 'ad'
        stale = {k: 'not_met' for k in fields if k.startswith(other + '_')}
        assert evaluate(PACK, dict(facts, **stale)).decision == 'pass'
        assert evaluate(PACK, _coerce_patient(dict(facts, age_years='18'))).decision == 'pass'
        for clause in PACK['criteria']:
            if 'when' in clause:
                assert clause['when'] == fields[clause['id']]['when']
                assert _when_applies(clause['when'], facts) == clause['id'].startswith(path + '_')
    assert 'vitiligo_pde4_step' not in fields
    assert evaluate(PACK, dict(facts_for('vitiligo'), vitiligo_bsa='up_to_20_percent')).decision == 'fail'


def test_metadata_notes_and_catalog():
    assert PACK['drug'] == dict(name='Opzelura', generic_name='ruxolitinib', therapeutic_class='jak-inhibitor-topical')
    assert PACK['source']['effective_date'] == '2022-11-01'
    assert PACK['encoding_status'] == 'partial' and PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for phrase in ['10% BSA without an inequality', 'exactly age 17', 'infections', 'skin cancers',
                   'Cytopenias', 'Thrombosis', 'MACE', '2 months', '1 year', 'stabilization',
                   'no serious adverse effects', '4 × 60gm tubes per 28 days', 'manual review']:
        assert phrase in notes
    catalog = load_rule_pack_catalog()
    assert catalog['opzelura'] == PACK
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 163
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 35
    assert (BASE / 'opzelura.json').read_bytes() == (BASE / 'rule_packs/opzelura.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (163, 35)
    assert status['next_candidate'] == 'vecamyl'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
