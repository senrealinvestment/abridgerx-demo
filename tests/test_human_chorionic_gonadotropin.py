"""Archived HCG eligibility and catalog integration."""
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
SLUG = 'human-chorionic-gonadotropin'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())

@pytest.mark.parametrize('male', [{'sex':'male'}, {'patient_male':True}, {'sex':'male','patient_male':True}, {'sex':None,'patient_male':True}])
def test_approval(male):
    assert evaluate(PACK, dict(indication='prepubertal_cryptorchidism', **male)).decision == 'pass'

@pytest.mark.parametrize('male', [{'sex':'female'}, {'sex':'other'}, {'patient_male':False}, {'sex':'male','patient_male':False}, {'sex':'female','patient_male':True}])
def test_not_male(male):
    assert evaluate(PACK, dict(indication='prepubertal_cryptorchidism', **male)).decision == 'fail'

@pytest.mark.parametrize('indication', ['infertility','weight_loss','other','off_label','cryptorchidism',True])
def test_excluded_indication(indication):
    assert evaluate(PACK, dict(indication=indication, sex='male')).decision == 'fail'

@pytest.mark.parametrize('patient,missing', [({}, ['indication','patient_male','sex']), ({'sex':'male'}, ['indication']), ({'sex':'male','indication':None}, ['indication']), ({'indication':'prepubertal_cryptorchidism'}, ['patient_male','sex'])])
def test_missing(patient, missing):
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert sorted(result.missing_facts) == missing

def test_ui():
    detail = drug_detail(SLUG)
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == {'sex','patient_male','indication'}
    for field, value in [('sex','male'), ('patient_male','yes')]:
        assert evaluate(PACK, _coerce_patient({field:value,'indication':'prepubertal_cryptorchidism'})).decision == 'pass'

def test_catalog_and_source():
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2019-01-15'
    assert PACK['max_units'] is None
    assert 'No authorization duration or quantity limit' in ' '.join(PACK['notes'])
    assert (BASE/f'{SLUG}.json').read_bytes() == (BASE/'rule_packs'/f'{SLUG}.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog[SLUG] == PACK
    assert catalog['leuprolide']['encoding_status'] == 'partial'
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 167
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 31
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f:
        assert json.load(f) == catalog
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    assert json.loads((BASE/'ENCODING_STATUS.json').read_text())['next_candidate'] == 'gralise'
