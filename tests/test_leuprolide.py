"""Leuprolide's three independent approval paths and catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/leuprolide.json').read_text())
PATHS = [('central_precocious_puberty', 'patient_child', True),
         ('endometriosis', 'sex', 'female'),
         ('uterine_leiomyomata', 'sex', 'female'),
         ('advanced_prostate_cancer', 'sex', 'male')]

@pytest.mark.parametrize('indication,fact,value', PATHS)
def test_paths(indication, fact, value):
    patient = dict(indication=indication, **{fact: value})
    result = evaluate(PACK, patient)
    assert result.decision == 'pass'
    assert result.citations == [PACK['source']['citation']]
    for missing in [{}, {fact: None}]:
        result = evaluate(PACK, dict(indication=indication, **missing))
        assert result.decision == 'need_info'
        assert result.missing_facts == [fact]
    wrong = False if fact == 'patient_child' else ('male' if value == 'female' else 'female')
    assert evaluate(PACK, dict(patient, **{fact: wrong})).decision == 'fail'
    irrelevant = {'sex': 'other'} if fact == 'patient_child' else {'patient_child': False}
    assert evaluate(PACK, dict(patient, **irrelevant)).decision == 'pass'

@pytest.mark.parametrize('indication', ['other', 'prostate_cancer', '', True])
def test_closed_indication(indication):
    assert evaluate(PACK, dict(indication=indication, patient_child=True, sex='male')).decision == 'fail'

@pytest.mark.parametrize('patient', [{}, {'indication': None}, {'patient_child': True, 'sex': 'female'}])
def test_missing_indication(patient):
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == ['indication']

def test_ui():
    detail = drug_detail('leuprolide')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == {'indication', 'patient_child', 'sex'}
    assert fields['patient_child']['when'] == {'fact': 'indication', 'eq': 'central_precocious_puberty'}
    assert fields['sex']['when']['in'] == [p[0] for p in PATHS[1:]]
    for indication, fact, value in PATHS:
        assert evaluate(PACK, _coerce_patient(dict(indication=indication, **{fact: 'yes' if value is True else value}))).decision == 'pass'

def test_metadata_catalog():
    assert PACK['source']['effective_date'] is None
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for text in ['10/04/09', 'pharmacy', '5mg/mL', 'Lupron Depot-PED', 'Eligard', '45mg', 'up to 1 year', 'manual review', 'no numeric age cutoff']:
        assert text in notes
    assert (BASE/'leuprolide.json').read_bytes() == (BASE/'rule_packs/leuprolide.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['leuprolide'] == PACK
    assert catalog['lovaza']['encoding_status'] == 'partial'
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 190
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 8
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (190, 8, None)
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status']=='partial')
