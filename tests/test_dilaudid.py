"""Dilaudid IR: override, regimen branches, shared denials and catalog integrity."""
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
COMMON = ['pdmp_checked', 'failed_three_analgesics_or_inappropriate',
          'combo_opioid_analgesic_inappropriate', 'no_addictive_behaviors_or_sud_treatment',
          'prescribed_within_guidelines']
SAFETY = ['no_unmonitored_severe_asthma', 'no_gi_obstruction']


def pack():
    return json.loads((BASE / 'rule_packs/dilaudid.json').read_text())


def facts(path='single_agent'):
    patient = dict(indication='moderate_to_severe_pain', **{f: True for f in SAFETY})
    patient['pa_override_reason'] = 'hospice_or_cancer_or_ltc' if path == 'override' else 'standard_outpatient_path'
    if path != 'override':
        patient.update({f: True for f in COMMON})
        patient['opioid_regimen'] = path
        if path == 'single_agent':
            patient['daily_hydromorphone_ir_within_limit'] = True
        else:
            patient.update(concurrent_opioids_within_mme_limit=True, breakthrough_dosing_prn=True)
    return patient


@pytest.mark.parametrize('path', ['single_agent', 'concurrent_long_acting_opioid', 'override'])
def test_paths_missing_and_failed_facts(path):
    patient = facts(path)
    assert evaluate(pack(), patient).decision == 'pass'
    for key, value in patient.items():
        missing = dict(patient)
        del missing[key]
        result = evaluate(pack(), missing)
        assert result.decision == 'need_info', key
        assert key in result.missing_facts
        bad = dict(patient, **{key: False if value is True else 'unsupported'})
        assert evaluate(pack(), bad).decision == 'fail', key


@pytest.mark.parametrize('path', ['single_agent', 'concurrent_long_acting_opioid', 'override'])
def test_closed_indication_on_every_path(path):
    for value in ['yes', 'no', True, False, 'unknown', 'mild_pain']:
        assert evaluate(pack(), dict(facts(path), indication=value)).decision == 'fail'


def test_only_applicable_approval_facts_required():
    patient = facts('override')
    patient.update({f: False for f in COMMON})
    patient.update(opioid_regimen='unsupported', daily_hydromorphone_ir_within_limit=False,
                   concurrent_opioids_within_mme_limit=False, breakthrough_dosing_prn=False)
    assert evaluate(pack(), patient).decision == 'pass'
    assert evaluate(pack(), dict(facts(), concurrent_opioids_within_mme_limit=False,
                                 breakthrough_dosing_prn=False)).decision == 'pass'
    assert evaluate(pack(), dict(facts('concurrent_long_acting_opioid'),
                                 daily_hydromorphone_ir_within_limit=False)).decision == 'pass'
    assert evaluate(pack(), {}).decision == 'need_info'


def test_ui_gating_and_coercion():
    p = pack()
    detail = drug_detail('dilaudid')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        assert field['options'] == p['fact_ui'][key]['options']
        assert field.get('when') == p['fact_ui'][key].get('when')
    assert fields['indication']['when'] == {'fact': 'pa_override_reason', 'in': ['hospice_or_cancer_or_ltc', 'standard_outpatient_path']}
    assert [o['value'] for o in fields['indication']['options']] == ['moderate_to_severe_pain']
    for key in COMMON + ['opioid_regimen']:
        assert fields[key]['when'] == {'fact': 'pa_override_reason', 'eq': 'standard_outpatient_path'}
    for key in SAFETY:
        assert 'when' not in fields[key]
    for path in ['single_agent', 'concurrent_long_acting_opioid', 'override']:
        patient = {k: 'yes' if v is True else v for k, v in facts(path).items()}
        assert evaluate(p, _coerce_patient(patient)).decision == 'pass'
        patient['no_gi_obstruction'] = 'no'
        assert evaluate(p, _coerce_patient(patient)).decision == 'fail'


def test_metadata_and_catalog():
    p = pack()
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2020-01-06'
    assert 'inferred_required_facts' not in p and p['alternatives'] == []
    notes = ' '.join(p['notes'])
    for term in ['Version 2', '6/13/2007', '11/15/2019', '1/6/2020', '2/4/8 mg',
                 '1 mg/mL', '3 mg', '24 mg/day', 'numeric MME', '3 months',
                 '12 months', 'positive clinical improvement', '30-day supply',
                 'Benzodiazepines', 'respiratory depression', 'References:']:
        assert term in notes
    assert (BASE / 'dilaudid.json').read_bytes() == (BASE / 'rule_packs/dilaudid.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 185
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 13
    for slug in ['new-prescription-medications']:
        assert catalog[slug]['encoding_status'] == 'text_only'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (185, 13)
    assert status['next_candidate'] == 'new-prescription-medications'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
