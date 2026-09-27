"""Lovaza/Vascepa indication isolation, threshold boundaries and catalog mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/lovaza.json').read_text())
HTG = dict(product='lovaza', indication='hypertriglyceridemia', age_years=18,
           lipid_lowering_diet_and_exercise=True, baseline_tg_before_treatment_mg_dl=500,
           nontrial_medical_necessity_letter=True)
CV = dict(product='vascepa', indication='cardiovascular_risk_reduction', age_years=18,
          lipid_lowering_diet_and_exercise=True, prescribed_for_cv_risk_reduction=True,
          triglycerides_mg_dl=150.1, adjunct_maximally_tolerated_statin=True, established_cvd=True)

@pytest.mark.parametrize('patient', [HTG, dict(HTG, product='vascepa'), CV,
    dict(CV, established_cvd=False, diabetes_mellitus=True, additional_cv_risk_factor_count=2)])
def test_pass_and_required_missing(patient):
    assert evaluate(PACK, patient).decision == 'pass'
    for fact in patient:
        if fact == 'established_cvd' and patient.get('diabetes_mellitus'):
            continue  # Diabetes plus two risk factors independently satisfies this OR.
        incomplete = dict(patient); incomplete.pop(fact)
        result = evaluate(PACK, incomplete)
        assert result.decision == 'need_info', fact
        assert fact in result.missing_facts

@pytest.mark.parametrize('patient,fact,value', [
    (HTG, 'age_years', 17), (CV, 'age_years', 17),
    (HTG, 'baseline_tg_before_treatment_mg_dl', 499.9),
    (CV, 'triglycerides_mg_dl', 150), (CV, 'triglycerides_mg_dl', 149),
    (CV, 'product', 'lovaza'), (CV, 'adjunct_maximally_tolerated_statin', False),
    (CV, 'prescribed_for_cv_risk_reduction', False),
    (HTG, 'lipid_lowering_diet_and_exercise', False),
    (CV, 'lipid_lowering_diet_and_exercise', False),
    (HTG, 'product', 'other'), (HTG, 'indication', 'other')])
def test_denials(patient, fact, value):
    assert evaluate(PACK, dict(patient, **{fact: value})).decision == 'fail'

@pytest.mark.parametrize('drug', ['fibrate', 'niacin'])
@pytest.mark.parametrize('days,failed,decision', [(30, True, 'pass'), (29, True, 'fail'), (30, False, 'fail')])
def test_trials(drug, days, failed, decision):
    patient = dict(HTG, nontrial_medical_necessity_letter=False, fibrate_failed=False, niacin_failed=False)
    patient.update({drug+'_failed':failed, drug+'_trial_days':days})
    assert evaluate(PACK, patient).decision == decision

def test_letter_and_cvd_short_circuit():
    assert evaluate(PACK, dict(HTG, fibrate_failed=False, niacin_failed=False)).decision == 'pass'
    assert evaluate(PACK, dict(CV, diabetes_mellitus=False, additional_cv_risk_factor_count=0)).decision == 'pass'
    for diabetes, count in [(False, 2), (True, 1)]:
        assert evaluate(PACK, dict(CV, established_cvd=False, diabetes_mellitus=diabetes, additional_cv_risk_factor_count=count)).decision == 'fail'

def test_path_isolation():
    assert evaluate(PACK, dict(HTG, triglycerides_mg_dl=0, adjunct_maximally_tolerated_statin=False, established_cvd=False)).decision == 'pass'
    assert evaluate(PACK, dict(CV, baseline_tg_before_treatment_mg_dl=0, fibrate_failed=False, niacin_failed=False, nontrial_medical_necessity_letter=False)).decision == 'pass'
    result = evaluate(PACK, {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == {'product', 'indication', 'age_years', 'lipid_lowering_diet_and_exercise'}

def test_ui_and_metadata():
    fields = {f['key']: f for f in drug_detail('lovaza')['fact_fields']}
    for clause in PACK['criteria']:
        if clause.get('when', {}).get('fact') == 'indication':
            for fact in clause['required_facts']:
                if fact != 'product':
                    assert fields[fact]['when'] == clause['when']
    for patient in [HTG, CV]:
        raw = {k: ('yes' if v is True else str(v)) for k,v in patient.items()}
        assert evaluate(PACK, _coerce_patient(raw)).decision == 'pass'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2021-03-15'
    assert PACK['max_units']['quantity'] == 120
    assert (BASE/'lovaza.json').read_bytes() == (BASE/'rule_packs/lovaza.json').read_bytes()
    catalog = json.loads((BASE/'rule_packs_all.json').read_text())
    assert catalog['lovaza'] == PACK
    assert catalog['reclast']['encoding_status'] == 'partial'
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 171
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 27
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
