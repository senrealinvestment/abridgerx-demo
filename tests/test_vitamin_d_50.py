"""Drisdol indication alternatives, deficiency-only attestation and artifact consistency."""
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
PACK = json.loads((BASE / 'rule_packs/vitamin-d-50.json').read_text())
CLASS = 'not_dietary_supplement'
STEP = 'failed_1000_2000iu_daily_ge_6mo_labs_submitted'
PATHS = ['hypoparathyroidism', 'refractory_rickets', 'familial_hypophosphatemia',
         'secondary_hyperparathyroidism', 'vitamin_d_deficiency_failed_daily_otc']


def facts(path):
    return {'indication': path, CLASS: True, **({STEP: True} if path == PATHS[-1] else {})}


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


@pytest.mark.parametrize('path', PATHS[:-1])
def test_other_indications_bypass_daily_trial(path):
    for value in [None, False, True]:
        assert evaluate(PACK, dict(facts(path), **{STEP: value})).decision == 'pass'
    assert evaluate(PACK, dict(facts(PATHS[-1]), **{STEP: False})).decision == 'fail'
    assert evaluate(PACK, {}).missing_facts == ['indication']


@pytest.mark.parametrize('path', ['other', '', True, False, 'hypercholesterolemia_or_hyperlipidemia'])
def test_closed_request_path(path):
    result = evaluate(PACK, {'indication': path})
    assert result.decision == 'fail'
    assert result.missing_facts == []


def test_ui_gating_and_coercion():
    detail = drug_detail('vitamin-d-50')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == {'indication', CLASS, STEP}
    assert [o['value'] for o in fields['indication']['options']] == PATHS
    for clause in PACK['criteria'][1:]:
        assert fields[clause['id']]['when'] == clause['when']
    assert fields[STEP]['when'] == {'fact': 'indication', 'in': [PATHS[-1]]}
    for path in PATHS:
        ui = {k: 'yes' if v is True else v for k, v in facts(path).items()}
        assert evaluate(PACK, _coerce_patient(ui)).decision == 'pass'
        assert evaluate(PACK, _coerce_patient(dict(ui, **{CLASS: 'no'}))).decision == 'fail'


def test_source_scope_and_notes():
    assert PACK['source']['effective_date'] == '1970-01-01'
    source = json.loads((BASE / 'criteria_text/vitamin-d-50.json').read_text())
    assert PACK['source']['citation'] == source['source_url']
    assert PACK['encoding_status'] == 'partial'
    assert PACK['requires_pa'] is True
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for term in ['Version 1', '1/06/2011', '1/21/2011', '12 months', 'FDA indication',
                 'Clinical Pharmacology', 'package insert', '000-unit']:
        assert term in notes
    label = PACK['fact_ui'][STEP]['label']
    for term in ['compliantly', '1,000–2,000 IU', 'daily', 'at least 6 months',
                 'failed to correct', 'lab results submitted']:
        assert term in label
    assert len(PACK['criteria']) == 3


def test_catalog_and_mirrors():
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog['vitamin-d-50'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'vitamin-d-50.json').read_bytes() == (BASE / 'rule_packs/vitamin-d-50.json').read_bytes()
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 188
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 10
    for slug in ['hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc', '000-unit', 'soma', 'stadol', 'fexmid', 'ergocalciferol']:
        assert catalog[slug]['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (188, 10)
        assert status['next_candidate'] == 'hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
