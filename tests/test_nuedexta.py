"""Alaska Nuedexta approval gates, exclusions, and synchronized catalog."""
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
PACK = json.loads((BASE / 'rule_packs/nuedexta.json').read_text())
FACTS = dict(age_years=18, indication='pseudobulbar_affect',
             confirmed_pba_association='multiple_sclerosis', prescriber_specialty='neurologist',
             ssri_step='failed_therapeutic_dose', tca_step='failed_therapeutic_dose',
             baseline_cns_ls_score=13, prohibited_concomitant_drugs='absent',
             maoi_within_14_days='absent', prolonged_qt='absent', heart_failure='absent',
             complete_av_block='absent')

def test_closed_gates():
    assert evaluate(PACK, FACTS).decision == 'pass'
    for clause in PACK['criteria']:
        key = clause['id']
        if clause['predicate']['op'] != 'in':
            continue
        for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['other', 'yes', 'no', True, False]:
            result = evaluate(PACK, dict(FACTS, **{key: value}))
            allowed = value in clause['predicate']['values']
            assert result.decision == ('pass' if allowed else 'fail')
            assert [c['id'] for c in result.failed_clauses] == ([] if allowed else [key])
            assert clause['citation'] in result.citations

@pytest.mark.parametrize('key', list(FACTS))
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]

@pytest.mark.parametrize('key,value,decision', [
    ('age_years',17,'fail'), ('age_years',17.99,'fail'), ('age_years',18,'pass'),
    ('baseline_cns_ls_score',12,'fail'), ('baseline_cns_ls_score',12.99,'fail'),
    ('baseline_cns_ls_score',13,'pass'), ('baseline_cns_ls_score',35,'pass'),
])
def test_boundaries(key,value,decision):
    assert evaluate(PACK,dict(FACTS,**{key:value})).decision == decision

@pytest.mark.parametrize('ssri',['failed_therapeutic_dose','contraindicated','not_met'])
@pytest.mark.parametrize('tca',['failed_therapeutic_dose','contraindicated','not_met'])
def test_both_steps(ssri,tca):
    assert evaluate(PACK,dict(FACTS,ssri_step=ssri,tca_step=tca)).decision == ('fail' if 'not_met' in (ssri,tca) else 'pass')

@pytest.mark.parametrize('key',['prolonged_qt','heart_failure'])
def test_pacemaker_does_not_waive_other_cardiac_denials(key):
    assert evaluate(PACK,dict(FACTS,complete_av_block='with_implanted_pacemaker',**{key:'present'})).decision == 'fail'

def test_ui_metadata_and_notes():
    fields = {f['key']:f for f in drug_detail('nuedexta')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert all(f['type']=='select' and not f.get('free_text') for f in fields.values())
    assert [o['value'] for o in fields['indication']['options']] == ['pseudobulbar_affect']
    assert evaluate(PACK,_coerce_patient(dict(FACTS,age_years='18',baseline_cns_ls_score='13'))).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'dextromethorphan_quinidine'
    assert PACK['drug']['therapeutic_class'] == 'nmda-sigma'
    assert PACK['source']['effective_date'] == '2019-03-11'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    for phrase in ['pba-agent','Parkinson’s','Alzheimer’s','discrepancy','Thrombocytopenia','hepatitis','hypersensitivity','3 months','1 year','decreased laughing or crying','60 capsules/month','7 days','12 hours','manual review']:
        assert phrase in ' '.join(PACK['notes'])

def test_catalog_mirrors():
    catalog=load_rule_pack_catalog()
    assert catalog['nuedexta']==PACK
    assert catalog['interleukin-5-inhibitors']['encoding_status']=='partial'
    assert len(catalog)==198
    assert sum(p['encoding_status']=='partial' for p in catalog.values())==186
    assert sum(p['encoding_status']=='text_only' for p in catalog.values())==12
    assert (BASE/'nuedexta.json').read_bytes()==(BASE/'rule_packs/nuedexta.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text())==catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as stream:
        assert json.load(stream)==catalog
    status=json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'],status['encoding_text_only'])==(186,12)
    assert status['next_candidate']=='insulin-pens'
    assert status['partial_slugs']==sorted(k for k,v in catalog.items() if v['encoding_status']=='partial')
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes()==(BASE.parent/name).read_bytes()
