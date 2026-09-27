"""Archived Alaska Acthar criteria, indication isolation and denial boundaries."""
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
PACK = json.loads((BASE / 'rule_packs/h-p-acthar.json').read_text())
INDS = PACK['criteria'][0]['predicate']['values']
CI = [c['id'] for c in PACK['criteria'][1:12]]

def facts(ind=INDS[0]):
    f = dict.fromkeys(CI, False)
    f.update(indication=ind, clinic_notes_submitted=True, letter_of_medical_necessity_submitted=True)
    if ind == INDS[0]: f.update(age_years=1, lmn_documents_previous_treatments=True)
    elif ind == INDS[1]: f.update(age_years=18, current_ms_dmt=True, acute_ms_exacerbation=True, corticosteroid_trial_failed=True)
    else: f.update(lmn_documents_previous_treatments=True, peer_reviewed_study_support_submitted=True)
    return f

@pytest.mark.parametrize('ind', INDS)
def test_paths_and_missing(ind):
    f = facts(ind)
    assert evaluate(PACK, f).decision == 'pass'
    for key in f:
        for omit in [True, False]:
            missing = dict(f, **{key: None})
            if omit: del missing[key]
            r = evaluate(PACK, missing)
            assert r.decision == 'need_info'
            assert key in r.missing_facts
    for key in CI + ['clinic_notes_submitted','letter_of_medical_necessity_submitted']:
        r = evaluate(PACK, dict(f, **{key: key in CI}))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == [key]
    assert evaluate(PACK, dict(f, indication='other')).decision == 'fail'
    if ind != INDS[1]:
        assert evaluate(PACK, dict(f, lmn_documents_previous_treatments=False)).decision == 'fail'
    if ind in INDS[2:]:
        assert evaluate(PACK, dict(f, peer_reviewed_study_support_submitted=False)).decision == 'fail'
        assert any('Second-level review required' in n for n in evaluate(PACK, f).notes)

@pytest.mark.parametrize('ind,age,decision', [(INDS[0],0,'pass'),(INDS[0],1.99,'pass'),(INDS[0],2,'fail'),(INDS[1],17.99,'fail'),(INDS[1],18,'pass')])
def test_age(ind,age,decision):
    assert evaluate(PACK,dict(facts(ind),age_years=age)).decision == decision

@pytest.mark.parametrize('trial', [True,False,None])
@pytest.mark.parametrize('ci', [True,False,None])
def test_steroid_or(trial,ci):
    r = evaluate(PACK,dict(facts(INDS[1]),corticosteroid_trial_failed=trial,corticosteroid_contraindication_or_intolerance=ci))
    assert r.decision == ('pass' if True in (trial,ci) else 'need_info' if None in (trial,ci) else 'fail')

@pytest.mark.parametrize('key',['current_ms_dmt','acute_ms_exacerbation'])
def test_ms_denials(key):
    assert evaluate(PACK,dict(facts(INDS[1]),**{key:False})).decision == 'fail'

def test_isolation_ui_and_metadata():
    assert set(evaluate(PACK,{}).missing_facts) == set(CI + ['indication','clinic_notes_submitted','letter_of_medical_necessity_submitted'])
    for ind in INDS:
        f=facts(ind)
        # Inapplicable stale answers must not affect another branch.
        if ind != INDS[1]:f.update(current_ms_dmt=False,acute_ms_exacerbation=False,corticosteroid_trial_failed=False,corticosteroid_contraindication_or_intolerance=False)
        if ind in INDS[:2]:f['peer_reviewed_study_support_submitted']=False
        if ind in INDS[2:]:f['age_years']=99
        assert evaluate(PACK,f).decision == 'pass'
        wire={k:('yes' if v is True else 'no' if v is False else str(v)) for k,v in f.items()}
        assert evaluate(PACK,_coerce_patient(wire)).decision == 'pass'
    fields={f['key']:f for f in drug_detail('h-p-acthar')['fact_fields']}
    assert fields['current_ms_dmt']['when']['in'] == INDS[1:2]
    assert fields['peer_reviewed_study_support_submitted']['when']['in'] == INDS[2:]
    assert PACK['source']['effective_date']=='2018-08-17'
    assert PACK['drug']['therapeutic_class']=='acth-analogue'
    assert PACK['encoding_status']=='partial' and PACK['max_units'] is None
    for phrase in ['1/15/2019','80 unit/mL','21 days','4 weeks','80 units/day','30 mL = 6 vials','positive clinical response','Mechanism of action']:
        assert phrase in ' '.join(PACK['notes'])

def test_catalog():
    catalog=load_rule_pack_catalog()
    assert catalog['h-p-acthar']==PACK
    assert (BASE/'h-p-acthar.json').read_bytes()==(BASE/'rule_packs/h-p-acthar.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text())==catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f:assert json.load(f)==catalog
    assert len(catalog)==198
    assert sum(p['encoding_status']=='partial' for p in catalog.values())==186
    assert sum(p['encoding_status']=='text_only' for p in catalog.values())==12
    assert catalog['interleukin-5-inhibitors']['encoding_status']=='partial'
    for slug in ['fasenra','nucala','cinqair']: assert catalog[slug]['encoding_status']=='partial'
    for root in [BASE,BASE.parent]:
        status=json.loads((root/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'],status['encoding_text_only'])==(186,12)
        assert status['next_candidate']=='insulin-pens'
