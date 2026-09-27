"""Marinol indication gating and archived Alaska criteria."""
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
PACK = json.loads((BASE / 'rule_packs/marinol.json').read_text())
PATHS = [('aids_anorexia_weight_loss', 'megestrol_failure_or_intolerance', 'prior_antiemetic_failure'),
         ('chemotherapy_induced_nausea_vomiting', 'prior_antiemetic_failure', 'megestrol_failure_or_intolerance')]

@pytest.mark.parametrize('indication,fact,other', PATHS)
def test_path_outcomes_and_isolation(indication, fact, other):
    patient = dict(indication=indication, **{fact: True})
    assert evaluate(PACK, patient).decision == 'pass'
    assert evaluate(PACK, dict(patient, **{other: False})).decision == 'pass'
    assert evaluate(PACK, dict(patient, **{fact: False, other: True})).decision == 'fail'
    for value in [None, 'missing']:
        incomplete = dict(patient)
        if value is None:
            incomplete[fact] = None
        else:
            del incomplete[fact]
        result = evaluate(PACK, incomplete)
        assert result.decision == 'need_info'
        assert set(result.missing_facts) == {fact}
    assert evaluate(PACK, _coerce_patient(dict(indication=indication, **{fact: 'yes'}))).decision == 'pass'
    assert evaluate(PACK, _coerce_patient(dict(indication=indication, **{fact: 'no'}))).decision == 'fail'

@pytest.mark.parametrize('indication', [None, 'missing', 'other'])
def test_indication_required(indication):
    patient = {fact: True for _, fact, _ in PATHS}
    if indication != 'missing':
        patient['indication'] = indication
    result = evaluate(PACK, patient)
    assert result.decision == ('fail' if indication == 'other' else 'need_info')
    if indication != 'other':
        assert set(result.missing_facts) == {'indication'}
    assert set(evaluate(PACK, {}).missing_facts) == {'indication'}

def test_ui_source_and_mirrors():
    fields = {f['key']: f for f in drug_detail('marinol')['fact_fields']}
    assert set(fields) == {'indication', 'megestrol_failure_or_intolerance', 'prior_antiemetic_failure'}
    for clause in PACK['criteria'][1:]:
        assert fields[clause['id']]['when'] == clause['when']
    assert PACK['drug']['generic_name'] == 'dronabinol'
    assert PACK['encoding_status'] == 'partial'
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for phrase in ['3/15/2013', '6 months', '2 doses per day', '30-day supply per chemotherapy cycle', 'Schedule III', 'chart notes', 'current chemotherapy schedule']:
        assert phrase in notes
    assert (BASE/'marinol.json').read_bytes() == (BASE/'rule_packs/marinol.json').read_bytes()
    catalog = json.loads((BASE/'rule_packs_all.json').read_text())
    assert catalog['marinol'] == PACK
    assert catalog['reclast']['encoding_status'] == 'partial'
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 198
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 0
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (198, 0, None)
