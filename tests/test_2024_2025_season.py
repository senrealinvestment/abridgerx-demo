"""Synagis season cohorts, shared requirements, conditional UI and catalog."""
import gzip
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail

BASE = ROOT / 'data/alaska/parsed'
SLUG = '2024-2025-season'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
SHARED = ['palivizumab_medical_necessity_over_nirsevimab', 'dose_within_covered_rsv_season']
PATHS = {
    'preterm_32_to_lt_35_weeks_no_cld_chd': ['born_aug19_or_after_season_window', 'has_rsv_risk_factor'],
    'preterm_29_to_lt_32_weeks_no_cld_chd': ['age_lt_6mo_at_season_start'],
    'preterm_lt_29_weeks': ['age_lt_12mo_at_season_start'],
    'airway_or_neuromuscular_compromising_secretions': ['airway_or_nm_condition', 'age_lt_12mo_at_season_start'],
    'hemodynamically_significant_chd': ['age_le_24mo_at_season_start', 'hemodynamically_significant_chd'],
    'chronic_lung_disease_of_prematurity': ['age_lt_24mo_at_season_start', 'cld_therapy_within_6mo_pre_season'],
}

@pytest.mark.parametrize('path', PATHS)
def test_each_cohort_and_required_fact(path):
    facts = dict(indication=path, **{k: True for k in PATHS[path] + SHARED})
    assert evaluate(PACK, facts).decision == 'pass'
    for key in PATHS[path] + SHARED:
        failed = evaluate(PACK, dict(facts, **{key: False}))
        assert failed.decision == 'fail'
        assert failed.citations == [PACK['source']['citation']]
        for value in ['omit', None]:
            missing = dict(facts, **{key: value})
            if value == 'omit':
                del missing[key]
            result = evaluate(PACK, missing)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
    stale = {key: False for keys in PATHS.values() for key in keys if key not in facts}
    assert evaluate(PACK, dict(stale, **facts)).decision == 'pass'
    raw = {k: 'yes' if v is True else v for k, v in facts.items()}
    assert evaluate(PACK, _coerce_patient(raw)).decision == 'pass'

@pytest.mark.parametrize('path', ['other', '', True, False, 'rsv_prophylaxis_high_risk'])
def test_closed_indication(path):
    result = evaluate(PACK, {'indication': path})
    assert result.decision == 'fail'
    assert result.missing_facts == []

@pytest.mark.parametrize('facts', [{}, {'indication': None}])
def test_missing_indication(facts):
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == ['indication']

def test_ui_and_gates():
    detail = drug_detail(SLUG)
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    assert [o['value'] for o in fields['indication']['options']] == list(PATHS)
    for clause in PACK['criteria'][1:]:
        key = clause['id']
        expected = list(PATHS) if key in SHARED else [p for p, keys in PATHS.items() if key in keys]
        assert clause['when'] == {'fact': 'indication', 'in': expected}
        assert fields[key]['when'] == PACK['fact_ui'][key]['when'] == clause['when']
        assert fields[key]['options'] == [{'value': 'yes', 'label': 'Yes'}, {'value': 'no', 'label': 'No'}]

def test_source_and_notes():
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2024-11-01'
    source = json.loads((BASE / 'criteria_text' / f'{SLUG}.json').read_text())
    assert PACK['source']['citation'] == source['source_url']
    assert 'inferred_required_facts' not in PACK
    assert len(PACK['criteria']) == 12
    notes = ' '.join(PACK['notes'])
    for term in ['09/13/2024', 'Version 1', '5 monthly', '3 monthly', '90 days', 'breakthrough', 'cardiopulmonary bypass', '10/1/2024', '>10%', '≥2', '100mg/mL', '50mg/0.5mL', 'AAP', 'ACIP']:
        assert term in notes

def test_catalog_and_mirrors():
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog[SLUG] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 198
    assert {k for k,v in catalog.items() if v['encoding_status'] == 'text_only'} == set()
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (198, 0, None)
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
