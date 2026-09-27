"""Oxycodone IR paths, source dose limits, formulation gates and catalog integrity."""
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
SLUG = 'oxycodone-hydrochloride-immediate-release'
COMMON = ['failed_two_non_opioid_therapies', 'combo_opioid_analgesic_inappropriate',
          'breakthrough_dosing_prn', 'no_addictive_behaviors_or_sud_treatment',
          'prescribed_within_guidelines']
PATHS = ['override', 'pediatric', 'single_agent', 'concomitant_oxycontin_er', 'solution', 'concentrate']


def pack():
    return json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())


def facts(path='single_agent'):
    p = dict(indication='moderate_to_severe_pain')
    if path == 'override':
        return dict(p, pa_override_population='hospice_or_cancer_or_ltc')
    if path == 'pediatric':
        return dict(p, pa_override_population='pediatric_postop_solution_le_90ml',
                    age_years=13, dosage_form='solution_10mg_10ml', post_procedure=True, quantity_le_90ml=True)
    p.update(pa_override_population='standard_outpatient_path', dosage_form='solid',
             opioid_regimen='single_agent', **{f: True for f in COMMON})
    if path == 'concomitant_oxycontin_er':
        p.update(opioid_regimen=path, active_oxycontin_pa=True, ir_for_breakthrough_pain=True,
                 total_daily_oxycodone_all_forms_le_160mg=True)
    else:
        p['single_agent_daily_oxycodone_le_90mg'] = True
    if path in ['solution', 'concentrate']:
        p.update(dosage_form='solution_10mg_10ml', unable_to_use_solid_dosage_form=True)
    if path == 'concentrate':
        p.update(dosage_form='concentrated_solution_20mg_ml', needs_concentrated_oral_solution=True)
    return p


@pytest.mark.parametrize('path', PATHS)
def test_paths_missing_and_failed_facts(path):
    patient = facts(path)
    assert evaluate(pack(), patient).decision == 'pass'
    for key, value in patient.items():
        missing = dict(patient)
        del missing[key]
        result = evaluate(pack(), missing)
        assert result.decision == 'need_info', (path, key)
        assert key in result.missing_facts
        bad_value = {'age_years': 14}.get(key, False if value is True else 'unsupported')
        assert evaluate(pack(), dict(patient, **{key: bad_value})).decision == 'fail', (path, key)


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('indication', ['yes', True, False, 'mild_pain', 'unknown'])
def test_closed_indication(path, indication):
    assert evaluate(pack(), dict(facts(path), indication=indication)).decision == 'fail'


@pytest.mark.parametrize('age,quantity,decision', [(13.99, True, 'pass'), (14, True, 'fail'), (13, False, 'fail')])
def test_pediatric_boundaries(age, quantity, decision):
    assert evaluate(pack(), dict(facts('pediatric'), age_years=age, quantity_le_90ml=quantity)).decision == decision


def test_branch_isolation_and_shared_prn():
    for path in ['override', 'pediatric']:
        p = facts(path)
        p.update({f: False for f in COMMON})
        p.update(unable_to_use_solid_dosage_form=False, needs_concentrated_oral_solution=False)
        assert evaluate(pack(), p).decision == 'pass'
    assert evaluate(pack(), dict(facts(), active_oxycontin_pa=False, ir_for_breakthrough_pain=False,
                                 total_daily_oxycodone_all_forms_le_160mg=False,
                                 unable_to_use_solid_dosage_form=False)).decision == 'pass'
    assert evaluate(pack(), dict(facts('concomitant_oxycontin_er'),
                                 single_agent_daily_oxycodone_le_90mg=False)).decision == 'pass'
    for path in ['single_agent', 'concomitant_oxycontin_er']:
        assert evaluate(pack(), dict(facts(path), breakthrough_dosing_prn=False)).decision == 'fail'
    assert evaluate(pack(), dict(facts('pediatric'), dosage_form='concentrated_solution_20mg_ml')).decision == 'fail'
    assert evaluate(pack(), {}).decision == 'need_info'


def test_ui_gating_and_coercion():
    p = pack()
    detail = drug_detail(SLUG)
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    for key, field in fields.items():
        assert field.get('when') == p['fact_ui'][key].get('when')
        if field['type'] == 'select':
            assert field['options'] == p['fact_ui'][key]['options']
            assert not field.get('free_text')
    assert fields['indication']['when'] == {'fact': 'pa_override_population', 'in': [
        'hospice_or_cancer_or_ltc', 'standard_outpatient_path', 'pediatric_postop_solution_le_90ml']}
    for key in COMMON + ['opioid_regimen']:
        assert fields[key]['when'] == {'fact': 'pa_override_population', 'eq': 'standard_outpatient_path'}
    for path in PATHS:
        patient = {k: 'yes' if v is True else str(v) if isinstance(v, int) else v for k, v in facts(path).items()}
        assert evaluate(p, _coerce_patient(patient)).decision == 'pass'


def test_metadata_and_catalog():
    p = pack()
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2020-01-06'
    assert 'inferred_required_facts' not in p
    notes = ' '.join(p['notes'])
    for term in ['Version 2', '06/23/2007', '11/15/2019', '1/6/2020', '5/7.5/10/15/20/30 mg',
                 '5 mg/5 mL', '20 mg/mL', '3 months', '12 months', 'positive response',
                 'Maximum Units Med List', 'hard-reject', 'Benzodiazepines', 'respiratory depression']:
        assert term in notes
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 180
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 18
    for slug in ['fexmid', 'brand-name-multisource-medications']:
        assert catalog[slug]['encoding_status'] == 'text_only'
    assert not json.loads((BASE / 'criteria_text/fexmid.json').read_text())['extracted_text'].strip()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (180, 18)
    assert status['next_candidate'] == 'brand-name-multisource-medications'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
