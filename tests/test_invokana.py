"""Invokana source requirements, missing evidence, and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/invokana.json').read_text())

def facts():
    return dict(indication='type_2_diabetes', diagnosis_documented=True,
                metformin_or_antidiabetic_failure=True, age_years=18)

def test_approval_and_ui():
    assert evaluate(PACK, facts()).decision == 'pass'
    assert evaluate(PACK, _coerce_patient(dict(indication='type_2_diabetes',
        diagnosis_documented='yes', metformin_or_antidiabetic_failure='yes', age_years='18'))).decision == 'pass'
    assert evaluate(PACK, {}).decision == 'need_info'
    detail = drug_detail('invokana')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(facts())
    assert all(f['type'] == 'select' and not f.get('free_text') for f in detail['fact_fields'])

@pytest.mark.parametrize('key', list(facts()))
@pytest.mark.parametrize('explicit_null', [False, True])
def test_missing_evidence(key, explicit_null):
    patient = facts()
    if explicit_null: patient[key] = None
    else: del patient[key]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert key in result.missing_facts

@pytest.mark.parametrize('key,value', [('indication','type_1_diabetes'),
    ('indication','diabetic_ketoacidosis'), ('indication','other'),
    ('diagnosis_documented',False), ('metformin_or_antidiabetic_failure',False),
    ('age_years',17.99)])
def test_denials(key, value):
    result = evaluate(PACK, dict(facts(), **{key:value}))
    assert result.decision == 'fail'
    assert key in {c['id'] for c in result.failed_clauses}

def test_metadata_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['invokana'] == PACK
    assert PACK['drug']['generic_name'] == 'canagliflozin'
    assert PACK['source']['effective_date'] == '2013-11-15'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    for phrase in ['SGLT2', '12 months', '30-day supply', '100mg up to 1 tablet per day', '300mg up to 1 tablet per day', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])
    assert (BASE/'invokana.json').read_bytes() == (BASE/'rule_packs/invokana.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f: assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 164
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 34
    assert catalog['leuprolide']['encoding_status'] == 'partial'
    for folder in [BASE,BASE.parent]:
        status=json.loads((folder/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'],status['encoding_text_only']) == (164,34)
        assert status['next_candidate']=='vimovo'
        assert status['partial_slugs']==sorted(k for k,v in catalog.items() if v['encoding_status']=='partial')
