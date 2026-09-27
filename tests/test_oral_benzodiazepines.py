"""Oral benzodiazepine request paths, denial scope, UI and catalog integrity."""
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
SLUG = 'oral-benzodiazepines'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
PATHS = ['quantity_limit_exception', 'three_or_more_benzodiazepines_30d', 'seizure_diagnosis']
PLAN = 'treatment_plan_and_medical_necessity'
DENIAL = 'not_concurrent_opioids_when_exceeding_ql'


def facts(path):
    return dict(indication=path, **{DENIAL: True}, **(
        {'seizure_diagnosis': True} if path == PATHS[2] else {PLAN: True, 'pdmp_checked': True}))


@pytest.mark.parametrize('path', PATHS)
def test_approval_and_required_facts(path):
    patient = facts(path)
    assert evaluate(PACK, patient).decision == 'pass'
    for key in patient:
        for missing in [None, 'omit']:
            modified = dict(patient, **{key: None})
            if missing == 'omit':
                del modified[key]
            result = evaluate(PACK, modified)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
        result = evaluate(PACK, dict(patient, **{key: False}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [key]
        assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('exceeds', [True, False])
@pytest.mark.parametrize('opioids', [True, False])
def test_combined_denial_attestation(path, exceeds, opioids):
    # This combined fact is attested after reviewing Table 1, not inferred by the engine.
    patient = dict(facts(path), **{DENIAL: not (exceeds and opioids)})
    assert evaluate(PACK, patient).decision == ('fail' if exceeds and opioids else 'pass')


def test_seizure_bypasses_plan_and_pdmp_but_not_denial():
    patient = dict(facts(PATHS[2]), **{PLAN: False, 'pdmp_checked': False})
    assert evaluate(PACK, patient).decision == 'pass'
    assert evaluate(PACK, dict(patient, **{DENIAL: False})).decision == 'fail'
    for path in PATHS[:2]:
        assert evaluate(PACK, dict(facts(path), seizure_diagnosis=False)).decision == 'pass'


@pytest.mark.parametrize('path', ['other', '', True, False])
def test_closed_path(path):
    result = evaluate(PACK, {'indication': path})
    assert result.decision == 'fail'
    assert result.missing_facts == []


def test_gating_ui_and_coercion():
    assert evaluate(PACK, {}).missing_facts == ['indication']
    detail = drug_detail(SLUG)
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == {'indication', PLAN, 'pdmp_checked', 'seizure_diagnosis', DENIAL}
    assert [o['value'] for o in PACK['fact_ui']['indication']['options']] == PATHS
    for criterion in PACK['criteria'][1:]:
        assert fields[criterion['id']]['when'] == criterion['when']
    for path in PATHS:
        patient = facts(path)
        assert set(evaluate(PACK, {'indication': path}).missing_facts) == set(patient) - {'indication'}
        ui = {k: 'yes' if v is True else v for k,v in patient.items()}
        assert evaluate(PACK, _coerce_patient(ui)).decision == 'pass'
        assert evaluate(PACK, _coerce_patient(dict(ui, **{DENIAL: 'no'}))).decision == 'fail'


def test_source_and_notes():
    source = json.loads((BASE / 'criteria_text' / f'{SLUG}.json').read_text())
    assert PACK['source']['citation'] == source['source_url']
    assert PACK['source']['effective_date'] == '2019-06-24'
    assert 'inferred_required_facts' not in PACK
    assert PACK['max_units'] is None
    assert PACK['requires_pa'] is True
    notes = ' '.join(PACK['notes'])
    for term in ['ALPRAZOLAM ER', 'CLONAZEPAM ODT', 'TRIAZOLAM', '900ML', '3 months', '12 months', 'positive response', 'GABAA', 'Version 1', '3/13/2019', '4/19/2019', '6/24/2019']:
        assert term in notes
    assert 'Kroll' in notes
    assert '"and"' in notes and 'and/or' in notes
def test_catalog_and_mirrors():
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog[SLUG] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 187
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 11
    assert catalog['genotypes']['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (187, 11)
        assert status['next_candidate'] == 'genotypes'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
