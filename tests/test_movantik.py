"""Movantik PA eligibility, safety denials, and catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/movantik.json').read_text())
GOOD = dict(indication='opioid_induced_constipation_chronic_noncancer_pain', age_years=18,
            currently_taking_opioid=True, otc_constipation_failure_one_week=True,
            gi_obstruction_or_recurrent_risk=False, strong_cyp3a4_inhibitor=False,
            moderate_cyp3a4_without_dose_adjustment=False)

def test_eligible_and_ui():
    assert evaluate(PACK, GOOD).decision == 'pass'
    patient = {k: ('yes' if v else 'no') if isinstance(v, bool) else str(v) for k,v in GOOD.items()}
    assert evaluate(PACK, _coerce_patient(patient)).decision == 'pass'
    assert {f['key'] for f in drug_detail('movantik')['fact_fields']} == set(GOOD)

@pytest.mark.parametrize('fact,value', [('indication','other'),('age_years',17),
    ('currently_taking_opioid',False),('otc_constipation_failure_one_week',False),
    ('gi_obstruction_or_recurrent_risk',True),('strong_cyp3a4_inhibitor',True),
    ('moderate_cyp3a4_without_dose_adjustment',True)])
def test_denials(fact,value):
    result = evaluate(PACK, dict(GOOD, **{fact:value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [fact]

@pytest.mark.parametrize('fact', GOOD)
@pytest.mark.parametrize('null', [False,True])
def test_missing(fact,null):
    patient = GOOD.copy()
    if null: patient[fact] = None
    else: del patient[fact]
    result = evaluate(PACK,patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]

def test_pos_does_not_bypass_pa():
    assert evaluate(PACK, {'opioid_claim_within_30_days':True}).decision == 'need_info'
    assert evaluate(PACK,dict(GOOD,age_years=17,opioid_claim_within_30_days=True)).decision == 'fail'

def test_metadata_and_catalog():
    assert PACK['source']['effective_date'] == '2016-11-30'
    assert PACK['drug']['generic_name'] == 'naloxegol'
    assert PACK['encoding_status'] == 'partial'
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for phrase in ['12.5 mg','25 mg','30 days','3 months','6 months','positive clinical response','1 tablet per day']:
        assert phrase in notes
    assert (BASE/'movantik.json').read_bytes() == (BASE/'rule_packs/movantik.json').read_bytes()
    catalog = json.loads((BASE/'rule_packs_all.json').read_text())
    assert catalog == {p.stem:json.loads(p.read_text()) for p in (BASE/'rule_packs').glob('*.json')}
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f: assert json.load(f) == catalog
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 165
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 33
    assert catalog['reclast']['encoding_status'] == 'partial'
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'],status['encoding_text_only'],status['next_candidate']) == (165,33,'transderm-scop')
