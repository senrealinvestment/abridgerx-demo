"""Cambia's nested NSAID exception and independent triptan alternatives."""
import gzip
import itertools
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
PACK = json.loads((BASE / 'rule_packs/cambia.json').read_text())
STEPS = ['two_nsaid_trials_including_diclofenac_tabs', 'unable_swallow_tablets',
         'liquid_nsaid_trial', 'two_triptan_trials', 'triptan_contraindication']
def facts():
    return dict(indication='migraine_with_or_without_aura', age_years=18,
                not_daily_use=True, no_hypersensitivity=True)
def tri_all(values):
    return False if False in values else None if None in values else True
def tri_any(values):
    return True if True in values else None if None in values else False
@pytest.mark.parametrize('values', list(itertools.product([True, False, None], repeat=5)))
def test_step_truth_table(values):
    a,b,c,d,e = values
    outcomes = [tri_any([a,tri_all([b,c])]), tri_any([d,e])]
    expected = 'need_info' if None in outcomes else 'fail' if False in outcomes else 'pass'
    assert evaluate(PACK, dict(facts(), **dict(zip(STEPS, values)))).decision == expected
@pytest.mark.parametrize('nsaid', [STEPS[:1], STEPS[1:3]])
@pytest.mark.parametrize('triptan', STEPS[3:])
def test_paths_missing_denials_and_ui(nsaid, triptan):
    patient = dict(facts(), **{k:True for k in nsaid+[triptan]})
    assert evaluate(PACK, patient).decision == 'pass'
    assert evaluate(PACK, _coerce_patient({k:'yes' if v is True else str(v) for k,v in patient.items()})).decision == 'pass'
    for key in patient:
        for explicit_null in [False, True]:
            incomplete = dict(patient)
            if explicit_null: incomplete[key] = None
            else: del incomplete[key]
            result = evaluate(PACK, incomplete)
            assert result.decision == 'need_info'
            assert key in result.missing_facts
    for key,value in [('age_years',17.99),('indication','other'),('not_daily_use',False),('no_hypersensitivity',False)]:
        assert evaluate(PACK,dict(patient,**{key:value})).decision == 'fail'
def test_metadata_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['cambia'] == PACK
    assert PACK['drug']['generic_name'] == 'diclofenac_potassium_powder'
    assert PACK['source']['effective_date'] == '2018-01-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert evaluate(PACK,{}).decision == 'need_info'
    notes = ' '.join(PACK['notes'])
    for phrase in ['cardiovascular','gastrointestinal','6 months','12 months','9 x 50 mg','manual review']:
        assert phrase in notes
    detail = drug_detail('cambia')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(PACK['fact_ui'])
    assert all(f['type']=='select' and not f.get('free_text') for f in detail['fact_fields'])
    assert (BASE/'cambia.json').read_bytes() == (BASE/'rule_packs/cambia.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f: assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 155
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 43
    for folder in [BASE,BASE.parent]:
        status=json.loads((folder/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'],status['encoding_text_only']) == (155,43)
        assert status['next_candidate']=='nizoral'
        assert status['partial_slugs']==sorted(k for k,v in catalog.items() if v['encoding_status']=='partial')
    assert catalog['leuprolide']['encoding_status']=='partial'
