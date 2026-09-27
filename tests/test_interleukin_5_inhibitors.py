"""Alaska IL-5 class: product/indication isolation and exact attestation bands."""
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
PACK = json.loads((BASE / 'rule_packs/interleukin-5-inhibitors.json').read_text())
EGPA = ['asthma', 'eosinophilia_gt_10_pct', 'mono_or_polyneuropathy', 'migratory_pulmonary_infiltrates', 'paranasal_sinus_abnormalities', 'biopsy_extravascular_eosinophils']
PATHS = [('nucala', i) for i in ['asthma','egpa','hes','crswnp','copd']] + [('fasenra','asthma'),('fasenra','egpa'),('cinqair','asthma')]
EOS = {'nucala':'nucala_asthma_eos','fasenra':'fasenra_asthma_eos_ge_150_4w','cinqair':'cinqair_asthma_eos_gt_400_4w'}
def facts(product='nucala', indication='asthma'):
    f=dict(product=product, indication=indication, fda_labeled_age=True, prescriber_specialty='allergist', not_used_with_another_biologic=True, not_acute_bronchospasm=True)
    if indication=='asthma':
        f.update(severe_asthma=True, asthma_controller_trial_3mo='ics_laba_ltra_or_theo_3mo', asthma_concurrent_controller=True)
        f[EOS[product]]='gt_150_within_6w' if product=='nucala' else True
    if indication=='egpa':f.update(egpa_acr_criteria=EGPA[:4],egpa_steroid_status='stable_4w')
    if indication=='hes':f.update(hes_duration_no_secondary_cause=True,hes_steroid_status='stable_4w')
    if indication=='crswnp':f.update(crswnp_imaging_or_exam_confirmed=True,crswnp_symptoms_ge_2_for_6mo=True,crswnp_incs_3mo_and_continue=True)
    if indication=='copd':f.update(copd_failed_triple_therapy_3mo=True,copd_exacerbation_history_met=True,copd_spirometry_criteria_met=True,nucala_copd_eos='ge_150_within_6w')
    return f

@pytest.mark.parametrize('product,indication',PATHS)
def test_paths_missing_and_denials(product,indication):
    f=facts(product,indication)
    assert evaluate(PACK,f).decision=='pass'
    for key in f:
        for null in [False,True]:
            g=dict(f)
            if null:g[key]=None
            else:del g[key]
            r=evaluate(PACK,g)
            assert r.decision=='need_info', (key,r)
            assert key in r.missing_facts
        if isinstance(f[key],bool):assert evaluate(PACK,dict(f,**{key:False})).decision=='fail'
    assert evaluate(PACK,dict(f,prescriber_specialty='other')).decision=='fail'
    wire={k:('yes' if v is True else 'no' if v is False else v) for k,v in f.items()}
    assert evaluate(PACK,_coerce_patient(wire)).decision=='pass'

@pytest.mark.parametrize('product', ['nucala','fasenra','cinqair'])
@pytest.mark.parametrize('indication', ['asthma','egpa','hes','crswnp','copd'])
def test_product_eligibility(product,indication):
    f=facts('nucala',indication)
    f.update(product=product,fasenra_asthma_eos_ge_150_4w=True,cinqair_asthma_eos_gt_400_4w=True)
    assert evaluate(PACK,f).decision==('pass' if (product,indication) in PATHS else 'fail')

@pytest.mark.parametrize('product,indication',PATHS)
def test_stale_other_path_answers(product,indication):
    f=facts(product,indication)
    for pr,ind in PATHS:
        for k,v in facts(pr,ind).items():
            if k not in f:f[k]=False if isinstance(v,bool) else [] if isinstance(v,list) else 'neither'
    assert evaluate(PACK,f).decision=='pass'

@pytest.mark.parametrize('product,indication,key,good,bad',[
 ('nucala','asthma','nucala_asthma_eos',['gt_150_within_6w','gt_300_past_12mo'],['neither','ge_150_within_6w','ge_300_past_12mo']),
 ('nucala','copd','nucala_copd_eos',['ge_150_within_6w','ge_300_past_12mo'],['neither','gt_150_within_4w']),
 ('fasenra','asthma',EOS['fasenra'],[True],[False]),
 ('cinqair','asthma',EOS['cinqair'],[True],[False]),
 ('nucala','asthma','asthma_controller_trial_3mo',['ics_laba_ltra_or_theo_3mo','intolerant_to_all'],['none','ics_only']),
 ('nucala','egpa','egpa_steroid_status',['stable_4w','ci_or_inappropriate'],['none','stable_3w']),
 ('nucala','hes','hes_steroid_status',['stable_4w','ci_or_inappropriate'],['none','stable_3w']),
])
def test_bands_and_alternatives(product,indication,key,good,bad):
    for value in good:assert evaluate(PACK,dict(facts(product,indication),**{key:value})).decision=='pass'
    for value in bad:assert evaluate(PACK,dict(facts(product,indication),**{key:value})).decision=='fail'

@pytest.mark.parametrize('count',range(7))
def test_egpa_count(count):
    assert evaluate(PACK,dict(facts('nucala','egpa'),egpa_acr_criteria=EGPA[:count]+['unrelated'])).decision==('pass' if count>=4 else 'fail')

@pytest.mark.parametrize('indication,allowed,rejected', [('asthma','pulmonologist','rheumatologist'),('egpa','rheumatologist','ent'),('hes','rheumatologist','ent'),('crswnp','ent','pulmonologist'),('copd','pulmonologist','rheumatologist')])
def test_specialties(indication,allowed,rejected):
    assert evaluate(PACK,dict(facts('nucala',indication),prescriber_specialty=allowed)).decision=='pass'
    assert evaluate(PACK,dict(facts('nucala',indication),prescriber_specialty=rejected)).decision=='fail'

def test_ui_catalog_and_metadata():
    assert set(evaluate(PACK,{}).missing_facts)=={'product','indication','fda_labeled_age','not_used_with_another_biologic','not_acute_bronchospasm'}
    fields={f['key']:f for f in drug_detail('interleukin-5-inhibitors')['fact_fields']}
    assert fields['egpa_acr_criteria']['when']=={'fact':'indication','in':['egpa']}
    assert fields[EOS['fasenra']]['when']=={'fact':'product','in':['fasenra']}
    assert PACK['source']['effective_date']=='2025-11-01'
    assert PACK['drug']['therapeutic_class']=='il5-inhibitor'
    assert PACK['encoding_status']=='partial' and PACK['max_units'] is None
    for phrase in ['hypersensitivity','eye symptoms','abruptly','vasculitic rash','3 months','12 months','30 mg','100 mg','300 mg','3 mg/kg']:
        assert phrase in ' '.join(PACK['notes'])
    catalog=load_rule_pack_catalog()
    assert catalog['interleukin-5-inhibitors']==PACK
    assert (BASE/'interleukin-5-inhibitors.json').read_bytes()==(BASE/'rule_packs/interleukin-5-inhibitors.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text())==catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f:assert json.load(f)==catalog
    assert len(catalog)==198
    assert sum(p['encoding_status']=='partial' for p in catalog.values())==152
    assert sum(p['encoding_status']=='text_only' for p in catalog.values())==46
    assert catalog['bone-resorption-inhibitors']['encoding_status']=='partial'
    for root in [BASE,BASE.parent]:
        s=json.loads((root/'ENCODING_STATUS.json').read_text())
        assert (s['encoding_partial'],s['encoding_text_only'])==(152,46)
        assert s['next_candidate']=='marinol'
