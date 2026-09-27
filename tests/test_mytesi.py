"""Mytesi source criteria and deterministic catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/mytesi.json').read_text())
GOOD = dict(indication='noninfectious_diarrhea_hiv_aids_on_art', age_years=18,
            art_claims_last_90_days=True, diarrhea_criteria_met=True,
            secondary_causes_ruled_out=True, loperamide_failed_or_contraindicated=True,
            atropine_diphenoxylate_failed_or_contraindicated=True)


def test_eligible_and_ui():
    assert evaluate(PACK, GOOD).decision == 'pass'
    patient = {k: ('yes' if v else 'no') if isinstance(v, bool) else str(v) for k,v in GOOD.items()}
    assert evaluate(PACK, _coerce_patient(patient)).decision == 'pass'
    assert {f['key'] for f in drug_detail('mytesi')['fact_fields']} == set(GOOD)


@pytest.mark.parametrize('fact', GOOD)
def test_each_requirement_must_pass(fact):
    value = 'other' if fact == 'indication' else 17 if fact == 'age_years' else False
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


def test_empty_and_both_steps_required():
    assert evaluate(PACK, {}).decision == 'need_info'
    patient = dict(GOOD, loperamide_failed_or_contraindicated=False,
                   atropine_diphenoxylate_failed_or_contraindicated=False)
    assert len(evaluate(PACK, patient).failed_clauses) == 2


def test_metadata_and_catalog():
    assert PACK['source']['effective_date'] == '2021-05-24'
    assert PACK['drug']['generic_name'] == 'crofelemer'
    assert PACK['encoding_status'] == 'partial'
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for phrase in ['infectious etiologies', '3 months', '12 months', '60 tablets', '125 mg', '30 days']:
        assert phrase in notes
    assert (BASE/'mytesi.json').read_bytes() == (BASE/'rule_packs/mytesi.json').read_bytes()
    catalog = json.loads((BASE/'rule_packs_all.json').read_text())
    assert catalog == {p.stem:json.loads(p.read_text()) for p in (BASE/'rule_packs').glob('*.json')}
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f: assert json.load(f) == catalog
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 158
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 40
    assert catalog['reclast']['encoding_status'] == 'partial'
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'],status['encoding_text_only'],status['next_candidate']) == (158,40,'quinine')
