"""Nizoral source criteria and deterministic catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/nizoral.json').read_text())
GOOD = dict(indication='blastomycosis', prior_antifungal_trial_dates=True,
            baseline_liver_labs=True, no_history_of_liver_disease=True,
            box_warnings_discussed=True)


def test_eligible_and_ui():
    assert evaluate(PACK, GOOD).decision == 'pass'
    patient = {k: ('yes' if v else 'no') if isinstance(v, bool) else str(v) for k,v in GOOD.items()}
    assert evaluate(PACK, _coerce_patient(patient)).decision == 'pass'
    assert {f['key'] for f in drug_detail('nizoral')['fact_fields']} == set(GOOD)


@pytest.mark.parametrize('fact', GOOD)
def test_each_requirement_must_pass(fact):
    value = 'other' if fact == 'indication' else False
    result = evaluate(PACK, dict(GOOD, **{fact: value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [fact]


@pytest.mark.parametrize('fact', GOOD)
@pytest.mark.parametrize('null', [False, True])
def test_missing(fact, null):
    patient = GOOD.copy()
    if null: patient[fact] = None
    else: del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('indication', ['blastomycosis', 'coccidioidomycosis',
    'histoplasmosis', 'chromomycosis', 'paracoccidioidomycosis'])
def test_all_allowed_diagnoses(indication):
    assert evaluate(PACK, dict(GOOD, indication=indication)).decision == 'pass'


@pytest.mark.parametrize('indication', ['fungal_meningitis', 'candidiasis', 'other'])
def test_excluded_diagnoses(indication):
    assert evaluate(PACK, dict(GOOD, indication=indication)).decision == 'fail'


def test_empty():
    assert evaluate(PACK, {}).decision == 'need_info'


def test_metadata_and_catalog():
    assert PACK['source']['effective_date'] == '2022-06-01'
    assert PACK['drug']['generic_name'] == 'ketoconazole'
    assert PACK['encoding_status'] == 'partial'
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for phrase in ['hepatic risk', '1 month', '2 tablets per day', '200 mg', '30-day supply', 'Fungal meningitis']:
        assert phrase in notes
    assert (BASE/'nizoral.json').read_bytes() == (BASE/'rule_packs/nizoral.json').read_bytes()
    catalog = json.loads((BASE/'rule_packs_all.json').read_text())
    assert catalog == {p.stem:json.loads(p.read_text()) for p in (BASE/'rule_packs').glob('*.json')}
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f: assert json.load(f) == catalog
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 180
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 18
    assert catalog['reclast']['encoding_status'] == 'partial'
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'],status['encoding_text_only'],status['next_candidate']) == (180,18,'brand-name-multisource-medications')
