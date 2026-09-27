"""Revatio source approval gates, notes-only limits, UI and catalog integrity."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, find_alternatives
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/revatio.json').read_text())
FACTS = dict(indication='pulmonary_arterial_hypertension_who_group_1',
             current_nitrate_therapy='no_current_use', age_years=18)


@pytest.mark.parametrize('key,value,decision', [
    ('indication', FACTS['indication'], 'pass'),
    ('indication', 'who_group_1_pah', 'fail'),
    ('indication', 'pulmonary_hypertension_who_group_2', 'fail'),
    ('indication', 'erectile_dysfunction', 'fail'),
    ('current_nitrate_therapy', 'current_use', 'fail'),
    ('current_nitrate_therapy', 'no_current_use', 'pass'),
    ('current_nitrate_therapy', 'unknown', 'fail'),
    ('current_nitrate_therapy', True, 'fail'),
    ('current_nitrate_therapy', False, 'fail'),
    ('age_years', 17.99, 'fail'), ('age_years', 18, 'pass'),
    ('age_years', 90, 'pass'),
])
def test_gates(key, value, decision):
    result = evaluate(PACK, dict(FACTS, **{key: value}))
    assert result.decision == decision
    assert [c['id'] for c in result.failed_clauses] == ([key] if decision == 'fail' else [])
    assert result.citations


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


def test_all_missing_and_combined_failures():
    assert set(evaluate(PACK, {}).missing_facts) == set(FACTS)
    result = evaluate(PACK, dict(indication='other', age_years=17, current_nitrate_therapy='current_use'))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == set(FACTS)


def test_ui_and_notes_only_limits():
    detail = drug_detail('revatio')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == [FACTS['indication']]
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{key: option['value']})))
            assert result.decision in ['pass', 'fail']
    assert evaluate(PACK, _coerce_patient(dict(FACTS, age_years='18'))).decision == 'pass'
    assert evaluate(PACK, dict(FACTS, concurrent_bosentan=True, requested_units=1000)).decision == 'pass'
    assert PACK['max_units'] is None and len(PACK['criteria']) == 3
    assert all('when' not in c for c in PACK['criteria'])
    assert 'inferred_required_facts' not in PACK
    assert PACK['drug'] == dict(name='Revatio', generic_name='sildenafil', therapeutic_class='pde5-inhibitor')
    assert PACK['source']['effective_date'] == '2012-01-01'
    assert PACK['encoding_status'] == 'partial'
    for phrase in ['20mg', '10mg/12.5mL', 'bosentan', '12 months', '30-day supply', '#90 tablets', '#90 vials', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])


def test_catalog_mirrors_and_alternatives():
    catalog = load_rule_pack_catalog()
    assert catalog['revatio'] == PACK
    assert (BASE / 'revatio.json').read_bytes() == (BASE / 'rule_packs/revatio.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 190
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 8
    assert PACK['alternatives'] == ['winrevair']
    assert 'revatio' in catalog['winrevair']['alternatives']
    assert find_alternatives(PACK, FACTS, catalog)[0]['verification'] == 'evaluate_need_info'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (190, 8)
        assert status['next_candidate'] == None
        assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
