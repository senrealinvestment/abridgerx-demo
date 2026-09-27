"""Archived AK Diclegis/Bonjesta eligibility and manual-review boundaries."""
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
PACK = json.loads((BASE / 'rule_packs/diclegis-bonjesta.json').read_text())

def facts():
    return dict(indication='nvp', conservative_management_failure=True, not_concurrent_maoi=True)

@pytest.mark.parametrize('indication', ['nvp', 'nausea_vomiting_of_pregnancy'])
def test_approval_and_ui(indication):
    patient = dict(facts(), indication=indication)
    assert evaluate(PACK, patient).decision == 'pass'
    assert evaluate(PACK, _coerce_patient({k: 'yes' if v is True else v for k,v in patient.items()})).decision == 'pass'

@pytest.mark.parametrize('key', list(facts()))
@pytest.mark.parametrize('explicit_null', [False, True])
def test_missing(key, explicit_null):
    patient = facts()
    if explicit_null: patient[key] = None
    else: del patient[key]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert key in result.missing_facts

@pytest.mark.parametrize('key,value', [('indication','other'), ('conservative_management_failure',False), ('not_concurrent_maoi',False)])
def test_denials(key, value):
    result = evaluate(PACK, dict(facts(), **{key:value}))
    assert result.decision == 'fail'
    assert key in {c['id'] for c in result.failed_clauses}

def test_metadata_mirrors_and_manual_review():
    catalog = load_rule_pack_catalog()
    assert catalog['diclegis-bonjesta'] == PACK
    assert PACK['source']['effective_date'] == '2022-04-15'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert evaluate(PACK, {}).decision == 'need_info'
    notes = ' '.join(PACK['notes'])
    for phrase in ['3 months', 'Diclegis 120 tablets per 30 days', 'Bonjesta 60 tablets per 30 days', '10 mg/10 mg', '20 mg/20 mg', 'manual review', 'MAOI']:
        assert phrase in notes
    detail = drug_detail('diclegis-bonjesta')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(PACK['fact_ui'])
    assert all(f['type'] == 'select' and not f.get('free_text') for f in detail['fact_fields'])
    assert (BASE/'diclegis-bonjesta.json').read_bytes() == (BASE/'rule_packs/diclegis-bonjesta.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as f: assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 160
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 38
    for folder in [BASE, BASE.parent]:
        status = json.loads((folder/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (160,38)
        assert status['next_candidate'] == 'viberzi'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status']=='partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    assert catalog['fentora']['encoding_status'] == 'partial'
