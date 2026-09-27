"""Spravato shared gates, closed indications, safety and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/spravato.json').read_text())
FACTS = dict(indication='treatment_resistant_depression', age_years=18,
 prescriber_specialty='psychiatrist_or_consult', baseline_depression_score='hamd17',
 direct_supervision='confirmed', blood_pressure_monitoring='confirmed',
 antidepressant_class_trials='met', augmentation_trial='met', prescriber_rems='enrolled',
 aneurysmal_vascular_disease_or_avm='absent', intracerebral_hemorrhage='absent',
 psychosis_history='absent', benefits_outweigh_risks_attestation='attested')
INDICATIONS = ['treatment_resistant_depression','mdd_with_acute_suicidal_ideation_or_behavior']

@pytest.mark.parametrize('indication', INDICATIONS)
@pytest.mark.parametrize('key', [k for k in FACTS if k != 'age_years'])
def test_closed_gates(indication,key):
    clause = next(c for c in PACK['criteria'] if c['id']==key)
    for value in clause['predicate']['values'] + ['other','unknown',True,False]:
        facts = dict(FACTS, indication=indication)
        facts[key] = value
        result = evaluate(PACK, facts)
        good = value in clause['predicate']['values']
        assert result.decision == ('pass' if good else 'fail')
        assert {c['id'] for c in result.failed_clauses} == (set() if good else {key})
        assert result.citations

@pytest.mark.parametrize('indication',INDICATIONS)
@pytest.mark.parametrize('key',FACTS)
@pytest.mark.parametrize('omit',[True,False])
def test_missing(indication,key,omit):
    facts=dict(FACTS,indication=indication);facts[key]=None
    if omit: del facts[key]
    result=evaluate(PACK,facts)
    assert result.decision=='need_info'
    assert result.missing_facts==[key]

@pytest.mark.parametrize('age,decision',[(17,'fail'),(18,'pass'),(65,'pass')])
@pytest.mark.parametrize('indication',INDICATIONS)
def test_age(age,decision,indication):
    assert evaluate(PACK,dict(FACTS,age_years=age,indication=indication)).decision==decision

@pytest.mark.parametrize('history,attestation,decision',[
 ('absent','attested','pass'),('present','attested','fail'),
 ('absent','not_attested','fail'),('present','not_attested','fail')])
@pytest.mark.parametrize('indication',INDICATIONS)
def test_psychosis_or_no_attestation(history,attestation,decision,indication):
    assert evaluate(PACK,dict(FACTS,indication=indication,psychosis_history=history,
      benefits_outweigh_risks_attestation=attestation)).decision==decision

def test_ui_metadata_and_notes():
    detail=drug_detail('spravato')
    assert detail['can_evaluate']
    fields={f['key']:f for f in detail['fact_fields']}
    assert set(fields)==set(FACTS)
    assert len(fields['indication']['options'])==2
    assert all(not f.get('free_text') for f in fields.values())
    assert evaluate(PACK,_coerce_patient({k:str(v) for k,v in FACTS.items()})).decision=='pass'
    assert PACK['drug']['generic_name']=='esketamine'
    assert PACK['drug']['therapeutic_class']=='nmda-antagonist'
    assert PACK['source']['effective_date']=='2023-01-02'
    assert PACK['encoding_status']=='partial'
    assert PACK['max_units'] is None and 'inferred_required_facts' not in PACK
    assert len(PACK['criteria'])==13
    assert all('when' not in c for c in PACK['criteria'])
    notes=' '.join(PACK['notes'])
    for phrase in ['3 months','12 months','baseline depression score','56mg','84mg','twice weekly','J0013','anesthetic','preventing suicide','fetal harm','manual review']:
        assert phrase in notes

def test_catalog():
    catalog=load_rule_pack_catalog()
    assert catalog['spravato']==PACK
    assert catalog['uptravi']['encoding_status']=='partial'
    assert (BASE/'spravato.json').read_bytes()==(BASE/'rule_packs/spravato.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text())==catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f: assert json.load(f)==catalog
    assert len(catalog)==198
    assert sum(v['encoding_status']=='partial' for v in catalog.values())==166
    assert sum(v['encoding_status']=='text_only' for v in catalog.values())==32
    for d in [BASE,BASE.parent]:
        status=json.loads((d/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'],status['encoding_text_only'])==(166,32)
        assert status['next_candidate']=='zanaflex'
        assert status['partial_slugs']==sorted(k for k,v in catalog.items() if v['encoding_status']=='partial')
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes()==(BASE.parent/name).read_bytes()
