"""Archived Alaska Subsys eligibility, UI, and catalog boundaries."""
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
PACK = json.loads((BASE / 'rule_packs/subsys.json').read_text())

def facts():
    return dict(indication='cancer_breakthrough_pain', age_years=18,
                already_receiving_around_the_clock_opioid_for_cancer_pain=True, opioid_tolerant_for_persistent_cancer_pain=True)

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

@pytest.mark.parametrize('key,value', [('indication','cancer_pain'), ('indication','non_cancer_pain'), ('indication','other'), ('indication',True), ('already_receiving_around_the_clock_opioid_for_cancer_pain',False), ('opioid_tolerant_for_persistent_cancer_pain',False)])
def test_denial(key, value):
    result = evaluate(PACK, dict(facts(), **{key:value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [{'indication': 'indication_fda_labeled'}.get(key, key)]

def test_ui_and_empty():
    assert evaluate(PACK, {}).decision == 'need_info'
    detail = drug_detail('subsys')
    assert detail['can_evaluate']
    fields = {f['key']:f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert all(f['type']=='select' and not f.get('free_text') for f in fields.values())
    patient = dict(indication='cancer_breakthrough_pain', age_years='18', already_receiving_around_the_clock_opioid_for_cancer_pain='yes', opioid_tolerant_for_persistent_cancer_pain='yes')
    assert evaluate(PACK, _coerce_patient(patient)).decision == 'pass'
    for key in ['already_receiving_around_the_clock_opioid_for_cancer_pain','opioid_tolerant_for_persistent_cancer_pain']:
        assert evaluate(PACK, _coerce_patient(dict(patient, **{key:'no'}))).decision == 'fail'

def test_metadata_and_mirrors():
    assert PACK['drug']['generic_name'] == 'fentanyl sublingual spray'
    assert PACK['source']['effective_date'] == '1970-01-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert len(PACK['criteria']) == 4
    notes = ' '.join(PACK['notes'])
    for term in ['Version 1', '12/11/2012', '01/18/2013', '60 mg', '25 mcg/hour', '30 mg', '8 mg', 'equianalgesic', 'at least 1 week', '6 months', '30-day supply', 'TIRF REMS ACCESS', '100, 200, 400, 600, 800, 1200, 1600 mcg', 'oncologists', 'postoperative', 'inpatient', 'https://www.tirfremsaccess.com/TirfUI/rems/home.action']:
        assert term in notes
    assert 'inferred_required_facts' not in PACK
    assert {c['predicate']['fact'] for c in PACK['criteria']} == set(facts())
    assert PACK['alternatives'] == []
    catalog = load_rule_pack_catalog()
    assert catalog['subsys'] == PACK
    assert catalog['human-chorionic-gonadotropin']['encoding_status'] == 'partial'
    assert (BASE/'subsys.json').read_bytes() == (BASE/'rule_packs/subsys.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f: assert json.load(f) == catalog
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 178
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 20
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    status=json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'],status['encoding_text_only']) == (178,20)
    assert status['next_candidate'] == 'oral-buprenorphine-based-medication-assisted-therapy-office-based-opioid-treatme'


def test_indication_ui_gating():
    fields = {f['key']: f for f in drug_detail('subsys')['fact_fields']}
    assert fields['indication']['options'] == PACK['fact_ui']['indication']['options']
    for key in set(facts()) - {'indication'}:
        assert PACK['fact_ui'][key]['when'] == {'fact': 'indication', 'in': ['cancer_breakthrough_pain']}
        assert fields[key]['when'] == PACK['fact_ui'][key]['when']
    assert 'when' not in fields['indication']


@pytest.mark.parametrize('indication', ['acute_pain', 'postoperative_pain', 'persistent_cancer_pain', ''])
def test_closed_indication(indication):
    assert evaluate(PACK, dict(facts(), indication=indication)).decision == 'fail'
