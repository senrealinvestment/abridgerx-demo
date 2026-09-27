"""Archived Alaska Fentora eligibility, UI, and catalog boundaries."""
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
PACK = json.loads((BASE / 'rule_packs/fentora.json').read_text())

def facts():
    return dict(indication='breakthrough_cancer_pain', age_years=18,
                around_the_clock_opioid=True, opioid_tolerant=True)

@pytest.mark.parametrize('age,decision', [(0,'fail'), (17,'fail'), (17.9,'fail'), (18,'pass'), (65,'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(facts(), age_years=age)).decision == decision

@pytest.mark.parametrize('key', list(facts()))
@pytest.mark.parametrize('null', [False, True])
def test_missing(key, null):
    patient = facts()
    if null: patient[key] = None
    else: del patient[key]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]

@pytest.mark.parametrize('key,value', [('indication','cancer_pain'), ('indication','non_cancer_pain'), ('indication','other'), ('indication',True), ('around_the_clock_opioid',False), ('opioid_tolerant',False)])
def test_denial(key, value):
    result = evaluate(PACK, dict(facts(), **{key:value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]

def test_ui_and_empty():
    assert evaluate(PACK, {}).decision == 'need_info'
    detail = drug_detail('fentora')
    assert detail['can_evaluate']
    fields = {f['key']:f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert all(f['type']=='select' and not f.get('free_text') for f in fields.values())
    patient = dict(indication='breakthrough_cancer_pain', age_years='18', around_the_clock_opioid='yes', opioid_tolerant='yes')
    assert evaluate(PACK, _coerce_patient(patient)).decision == 'pass'
    for key in ['around_the_clock_opioid','opioid_tolerant']:
        assert evaluate(PACK, _coerce_patient(dict(patient, **{key:'no'}))).decision == 'fail'

def test_metadata_and_mirrors():
    assert PACK['drug']['generic_name'] == 'fentanyl_buccal'
    assert PACK['source']['effective_date'] == '2016-10-03'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert len(PACK['criteria']) == 4
    notes = ' '.join(PACK['notes'])
    for term in ['3/19/2010','60 mg/day','25 mcg/hour','30 mg/day','8 mg/day','equianalgesic','at least 1 week','6 months','30-day supply','90 tablets per 30 days','REMS','100, 200, 300, 400, 600 and 800 mcg']:
        assert term in notes
    catalog = load_rule_pack_catalog()
    assert catalog['fentora'] == PACK
    assert catalog['human-chorionic-gonadotropin']['encoding_status'] == 'partial'
    assert (BASE/'fentora.json').read_bytes() == (BASE/'rule_packs/fentora.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f: assert json.load(f) == catalog
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 158
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 40
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    status=json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'],status['encoding_text_only']) == (158,40)
    assert status['next_candidate'] == 'quinine'
