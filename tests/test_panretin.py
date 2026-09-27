"""Panretin approval clauses, missing evidence and UI integration."""
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog
B = ROOT / 'data/alaska/parsed'
PACK = json.loads((B / 'rule_packs/panretin.json').read_text())
FACTS = dict(indication='cutaneous_kaposi_sarcoma', not_systemic_ks_therapy=True)

def test_approval_and_ui():
    assert evaluate(PACK, FACTS).decision == 'pass'
    assert evaluate(PACK, _coerce_patient(dict(FACTS, not_systemic_ks_therapy='yes'))).decision == 'pass'
    assert evaluate(PACK, _coerce_patient(dict(FACTS, not_systemic_ks_therapy='no'))).decision == 'fail'
    detail = drug_detail('panretin')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(FACTS)
    assert all(f['type'] == 'select' and not f.get('free_text') for f in detail['fact_fields'])

@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('null', [False, True])
def test_missing_evidence(key, null):
    facts = FACTS.copy()
    if null: facts[key] = None
    else: del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert key in result.missing_facts

@pytest.mark.parametrize('key,value', [('indication', 'other'), ('indication', 'systemic_kaposi_sarcoma'), ('not_systemic_ks_therapy', False)])
def test_ineligible(key, value):
    result = evaluate(PACK, dict(FACTS, **{key: value}))
    assert result.decision == 'fail'
    assert key in {c['id'] for c in result.failed_clauses}

def test_metadata_and_scope():
    assert PACK['drug']['generic_name'] == 'alitretinoin'
    assert PACK['source']['effective_date'] == '2009-01-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert evaluate(PACK, {}).decision == 'need_info'
    assert (B/'panretin.json').read_bytes() == (B/'rule_packs/panretin.json').read_bytes()
    assert load_rule_pack_catalog()['panretin'] == PACK
    assert load_rule_pack_catalog()['symproic']['encoding_status'] == 'text_only'
    notes = ' '.join(PACK['notes'])
    for phrase in ['60 gram', 'AIDS-related', '06/04/2009', 'more than 10 new KS lesions', 'prior month', 'symptomatic lymphedema', 'symptomatic pulmonary KS', 'symptomatic visceral', 'no experience', '2 months', 'manual review']:
        assert phrase in notes
