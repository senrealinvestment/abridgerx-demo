"""Palforzia source gates, diagnostic alternatives, UI and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/palforzia.json').read_text())
FACTS = dict(indication='peanut_allergy', age_years=4,
             peanut_reaction_history='present',
             prescriber_specialty='immunologist_or_allergist_or_consult',
             peanut_ige_kua_l=0.35, peanut_ige_months_ago=12,
             peanut_spt_mm_vs_control=0, peanut_avoidance_diet='using',
             epinephrine_prescription='confirmed', uncontrolled_asthma='absent',
             esophagitis_or_eosinophilic_gi_history='absent',
             mast_cell_disorder_history='absent', recent_severe_anaphylaxis='absent')


@pytest.mark.parametrize('key', [k for k,v in FACTS.items() if isinstance(v,str)])
def test_closed_gates(key):
    for value in [FACTS[key], 'other', 'unknown', True, False]:
        result = evaluate(PACK, dict(FACTS, **{key:value}))
        assert result.decision == ('pass' if value == FACTS[key] else 'fail')
        assert {c['id'] for c in result.failed_clauses} == (set() if value == FACTS[key] else {key})
        assert result.citations


@pytest.mark.parametrize('age,decision', [(3,'fail'),(4,'pass'),(17,'pass'),(18,'fail')])
def test_age(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


@pytest.mark.parametrize('ige,months,spt,decision', [
    (0.35,12,0,'pass'), (0.349,12,2.99,'fail'), (0.35,12.01,0,'fail'),
    (None,None,3,'pass'), (0,24,3,'pass'), (0.35,12,3,'pass'),
    (0.35,12,None,'pass'), (None,None,2.99,'need_info'),
    (0.35,None,0,'need_info'), (0.349,12,None,'need_info'),
    (None,None,None,'need_info'),
])
def test_testing_paths(ige,months,spt,decision):
    result = evaluate(PACK, dict(FACTS, peanut_ige_kua_l=ige,
                      peanut_ige_months_ago=months, peanut_spt_mm_vs_control=spt))
    assert result.decision == decision
    if decision == 'fail':
        assert [c['id'] for c in result.failed_clauses] == ['peanut_allergy_testing']


@pytest.mark.parametrize('key', [k for k in FACTS if k != 'peanut_spt_mm_vs_control'])
@pytest.mark.parametrize('omit', [True,False])
def test_missing(key,omit):
    patient = dict(FACTS, **{key:None})
    if omit:
        del patient[key]
    result = evaluate(PACK,patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('key', ['uncontrolled_asthma','esophagitis_or_eosinophilic_gi_history',
                                'mast_cell_disorder_history','recent_severe_anaphylaxis'])
@pytest.mark.parametrize('spt_only',[True,False])
def test_denials_on_both_testing_paths(key,spt_only):
    patient = dict(FACTS, **{key:'present'})
    if spt_only:
        patient.update(peanut_ige_kua_l=None,peanut_ige_months_ago=None,peanut_spt_mm_vs_control=3)
    result = evaluate(PACK,patient)
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]


def test_ui_and_metadata():
    detail = drug_detail('palforzia')
    assert detail['can_evaluate']
    fields = {f['key']:f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert len(fields['indication']['options']) == 1
    assert all(not f.get('free_text') for f in fields.values())
    assert evaluate(PACK,_coerce_patient({k:str(v) for k,v in FACTS.items()})).decision == 'pass'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['drug'] == dict(name='Palforzia',generic_name='arachis_hypogaea_allergen_powder',therapeutic_class='oral-immunotherapy')
    assert PACK['source']['effective_date'] == '2021-01-11'
    assert len(PACK['criteria']) == 11
    assert all('when' not in c for c in PACK['criteria'])
    assert PACK['max_units'] is None and 'inferred_required_facts' not in PACK
    assert PACK['alternatives'] == []
    for phrase in ['3 months','12 months','34-day supply','60 minutes','epinephrine','eosinophilic esophagitis','manual review']:
        assert phrase in ' '.join(PACK['notes'])


def test_catalog():
    catalog = load_rule_pack_catalog()
    assert catalog['palforzia'] == PACK
    assert catalog['uptravi']['encoding_status'] == 'partial'
    assert (BASE/'palforzia.json').read_bytes() == (BASE/'rule_packs/palforzia.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status']=='partial' for v in catalog.values()) == 117
    assert sum(v['encoding_status']=='text_only' for v in catalog.values()) == 81
    for d in [BASE,BASE.parent]:
        status=json.loads((d/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'],status['encoding_text_only']) == (117,81)
        assert status['next_candidate'] == 'rhapsido'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status']=='partial')
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
