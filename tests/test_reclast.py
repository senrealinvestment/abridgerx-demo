"""Reclast/Zometa product isolation, clinical boundaries and missing evidence."""
import gzip
import json
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
B = ROOT / 'data/alaska/parsed'
PACK = json.loads((B / 'reclast.json').read_text())
R = dict(product='reclast', age_years=18, uncorrected_preexisting_hypocalcemia=False,
         currently_receiving_zometa=False, oral_bisphosphonate_contraindicated=True)
Z = dict(product='zometa', age_years=18, uncorrected_preexisting_hypocalcemia=False,
         currently_receiving_reclast=False)
CASES = [
 (R, 'postmenopausal_osteoporosis_treatment', dict(pretreatment_femoral_neck_or_spine_t_score=-2.5)),
 (R, 'postmenopausal_osteoporosis_treatment', dict(imaging_confirmed_osteoporotic_vertebral_fracture=True)),
 (R, 'postmenopausal_osteoporosis_treatment', dict(recent_low_trauma_hip_fracture=True)),
 (R, 'postmenopausal_osteoporosis_prevention', dict(femoral_neck_spine_or_total_hip_t_score=-1.1, frax_10_year_hip_percent=3)),
 (R, 'postmenopausal_osteoporosis_prevention', dict(femoral_neck_spine_or_total_hip_t_score=-1.1, frax_10_year_major_osteoporotic_percent=20)),
 (R, 'male_osteoporosis', dict(hypogonadal_osteoporosis=False)),
 (R, 'male_osteoporosis', dict(hypogonadal_osteoporosis=True, receiving_testosterone=True, high_fracture_risk_despite_testosterone=True)),
 (R, 'male_osteoporosis', dict(hypogonadal_osteoporosis=True, testosterone_contraindicated=True)),
 (R, 'glucocorticoid_induced_osteoporosis', dict(initiating_or_continuing_systemic_glucocorticoids=True, prednisone_equivalent_mg_per_day=7.5, expected_glucocorticoid_months=12)),
 (R, 'pagets_disease', dict(pagets_symptomatic=True)),
 (R, 'pagets_disease', dict(pagets_complication_risk=True)),
 (R, 'pagets_disease', dict(alkaline_phosphatase_age_specific_uln_multiple=2)),
 (Z, 'hypercalcemia_of_malignancy', dict(albumin_corrected_calcium_mg_dl=12)),
 (Z, 'multiple_myeloma', dict(concurrent_antineoplastic_therapy=True, calcium_and_vitamin_d_supplementation=True)),
 (Z, 'bone_metastases_from_solid_tumors', dict(concurrent_antineoplastic_therapy=True, calcium_and_vitamin_d_supplementation=True)),
]
@pytest.mark.parametrize('base,indication,evidence', CASES)
def test_paths_missing_and_ui(base, indication, evidence):
    facts=dict(base, indication=indication, **evidence)
    assert evaluate(PACK,facts).decision=='pass'
    raw={k:('yes' if v else 'no') if isinstance(v,bool) else str(v) for k,v in facts.items()}
    assert evaluate(PACK,_coerce_patient(raw)).decision=='pass'
    for key in facts:
        for null in (False,True):
            missing=facts.copy()
            if null: missing[key]=None
            else: del missing[key]
            result=evaluate(PACK,missing)
            assert result.decision=='need_info',key
            assert key in result.missing_facts
    for key,value in [('age_years',17),('uncorrected_preexisting_hypocalcemia',True),('indication','other'),('product','other')]:
        assert evaluate(PACK,dict(facts,**{key:value})).decision=='fail'
    key='currently_receiving_zometa' if base is R else 'currently_receiving_reclast'
    assert evaluate(PACK,dict(facts,**{key:True})).decision=='fail'

@pytest.mark.parametrize('base,indication,evidence', CASES)
def test_branch_failure_and_cross_product(base,indication,evidence):
    # Supply all alternate branch evidence as negative to distinguish failure from missing data.
    facts={k:False if v['type']=='select' else 0 for k,v in PACK['fact_ui'].items()}
    facts.update(base,indication=indication,**evidence)
    assert evaluate(PACK,facts).decision=='pass'
    for key,value in evidence.items():
        if key=='hypogonadal_osteoporosis': continue
        bad=False if isinstance(value,bool) else value+0.1 if 't_score' in key else value-0.1
        assert evaluate(PACK,dict(facts,**{key:bad})).decision=='fail',(key,bad)
    facts.update(product='zometa' if base is R else 'reclast',oral_bisphosphonate_contraindicated=True)
    assert evaluate(PACK,facts).decision=='fail'

def test_step_and_prevention_exact_boundary():
    f=dict(R,indication='pagets_disease',pagets_symptomatic=True,oral_bisphosphonate_contraindicated=False)
    assert evaluate(PACK,dict(f,oral_bisphosphonate_inadequate_response=True)).decision=='pass'
    assert evaluate(PACK,dict(f,oral_bisphosphonate_inadequate_response=False)).decision=='fail'
    f=dict(R,indication='postmenopausal_osteoporosis_prevention',femoral_neck_spine_or_total_hip_t_score=-1, frax_10_year_hip_percent=3)
    assert evaluate(PACK,f).decision=='fail'
    assert evaluate(PACK,{}).decision=='need_info'

def test_metadata_mirrors_and_scope():
    assert PACK['drug']['generic_name']=='zoledronic_acid'
    assert PACK['source']['effective_date']=='2022-03-01'
    assert (B/'reclast.json').read_bytes()==(B/'rule_packs/reclast.json').read_bytes()
    catalog=json.loads((B/'rule_packs_all.json').read_text())
    assert catalog=={p.stem:json.loads(p.read_text()) for p in (B/'rule_packs').glob('*.json')}
    with gzip.open(B/'rule_packs_all.json.gz','rt') as f: assert json.load(f)==catalog
    assert sum(p['encoding_status']=='partial' for p in catalog.values())==185
    assert sum(p['encoding_status']=='text_only' for p in catalog.values())==13
    for slug in ['new-prescription-medications','hemophilia','bactroban-cream','atypical-antipsychotic-therapeutic-duplication']:
        assert catalog[slug]['encoding_status']=='text_only'
    for c in PACK['criteria']:
        if c['id'].startswith(('reclast_', 'no_concurrent_zometa')): assert c['when']=={'fact':'product','eq':'reclast'}
        if c['id'].startswith(('zometa_', 'no_concurrent_reclast')): assert c['when']=={'fact':'product','eq':'zometa'}
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (B/name).read_bytes()==(B.parent/name).read_bytes()
