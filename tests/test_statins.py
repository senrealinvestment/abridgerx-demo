"""Statin step-edit paths, attestation alternatives, UI and artifact consistency."""
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
PACK = json.loads((BASE / 'rule_packs/statins.json').read_text())
CLASS = 'hypercholesterolemia_or_hyperlipidemia'
STEP = 'preferred_statin_75_of_90_days_inadequate_ldl_or_adr'
PATHS = ['preferred_statin', 'other_statin']


def facts(path):
    return {'indication': path, CLASS: True, **({STEP: True} if path == 'other_statin' else {})}


@pytest.mark.parametrize('path', PATHS)
def test_required_facts(path):
    patient = facts(path)
    assert evaluate(PACK, patient).decision == 'pass'
    for key in patient:
        for value in [None, 'omit']:
            modified = dict(patient, **{key: value})
            if value == 'omit':
                del modified[key]
            result = evaluate(PACK, modified)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
        result = evaluate(PACK, dict(patient, **{key: False}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [key]
        assert result.citations == [PACK['source']['citation']]


def test_preferred_bypasses_step():
    assert evaluate(PACK, dict(facts('preferred_statin'), **{STEP: False})).decision == 'pass'
    assert evaluate(PACK, dict(facts('other_statin'), **{STEP: False})).decision == 'fail'
    assert evaluate(PACK, {}).missing_facts == ['indication']


@pytest.mark.parametrize('path', ['other', '', True, False, 'hypercholesterolemia_or_hyperlipidemia'])
def test_closed_request_path(path):
    result = evaluate(PACK, {'indication': path})
    assert result.decision == 'fail'
    assert result.missing_facts == []


def test_ui_gating_and_coercion():
    detail = drug_detail('statins')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == {'indication', CLASS, STEP}
    assert [o['value'] for o in fields['indication']['options']] == PATHS
    for clause in PACK['criteria'][1:]:
        assert fields[clause['id']]['when'] == clause['when']
    assert fields[STEP]['when'] == {'fact': 'indication', 'in': ['other_statin']}
    for path in PATHS:
        ui = {k: 'yes' if v is True else v for k, v in facts(path).items()}
        assert evaluate(PACK, _coerce_patient(ui)).decision == 'pass'
        assert evaluate(PACK, _coerce_patient(dict(ui, **{CLASS: 'no'}))).decision == 'fail'


def test_source_scope_and_notes():
    assert PACK['source']['effective_date'] == '2024-03-01'
    assert PACK['source']['citation'] == json.loads((BASE / 'criteria_text/statins.json').read_text())['source_url']
    assert PACK['requires_pa'] is True
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for term in ['Version 2', '02/11/2013', '9/17/2010', '30-day', '1 tablet/day', '2 tablets or capsules/day', 'Lescol', 'Mevacor', 'Lovastatin', 'package insert', 'ADR alternative does not require a 75-day trial']:
        assert term in notes
    label = PACK['fact_ui'][STEP]['label']
    assert '75 of the last 90 days' in label and 'OR' in label


def test_catalog_and_mirrors():
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog['statins'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'statins.json').read_bytes() == (BASE / 'rule_packs/statins.json').read_bytes()
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 189
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 9
    for slug in ['2024-2025-season', '000-unit', 'soma', 'stadol', 'fexmid', 'ergocalciferol']:
        assert catalog[slug]['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (189, 9)
        assert status['next_candidate'] == '2024-2025-season'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
