"""Hetlioz indication isolation, formulation boundaries, denials and catalog parity."""
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
N = 'non_24_hour_sleep_wake_disorder'
S = 'smith_magenis_syndrome_nighttime_sleep_disturbances'


def pack():
    return json.loads((BASE / 'rule_packs/hetlioz.json').read_text())


def patient(indication):
    shared = dict(indication=indication, age_years=16, formulation='capsules',
                  prescriber_specialty='board_certified_sleep_specialist',
                  no_strong_cyp1a2_inhibitors=True, no_strong_cyp3a4_inducers=True,
                  no_severe_hepatic_impairment=True)
    if indication == N:
        shared.update(non24_diagnosis_confirmed=True, alternate_sleep_disorders_addressed=True,
                      non24_sleep_wake_schedule_failed=True, sighted_non24=True, light_therapy_trial_3_months=True)
    else:
        shared.update(sms_diagnosis_confirmed=True, nighttime_sleep_disturbances=True,
                      sms_sleep_wake_schedule_failed_with_logs=True)
    return shared


@pytest.mark.parametrize('indication', [N, S])
def test_required_facts_and_denials(indication):
    baseline = patient(indication)
    assert evaluate(pack(), baseline).decision == 'pass'
    for fact in baseline:
        for null in [False, True]:
            facts = baseline.copy()
            if null:
                facts[fact] = None
            else:
                del facts[fact]
            result = evaluate(pack(), facts)
            assert result.decision == 'need_info', fact
            assert fact in result.missing_facts
        if baseline[fact] is True and fact != 'sighted_non24':
            result = evaluate(pack(), dict(baseline, **{fact: False}))
            assert result.decision == 'fail'
            assert len(result.failed_clauses) == 1
    for c in pack()['criteria']:
        if c.get('when', {}).get('in', [indication]) != [indication]:
            for f in c['required_facts']:
                if f not in baseline:
                    assert evaluate(pack(), dict(baseline, **{f: False})).decision == 'pass'
    for invalid in ['other', 'non24', True, False]:
        assert evaluate(pack(), dict(baseline, indication=invalid)).decision == 'fail'
    for specialty in ['board_certified_sleep_specialist', 'board_certified_sleep_specialist_consult', 'other']:
        assert evaluate(pack(), dict(baseline, prescriber_specialty=specialty)).decision == ('fail' if specialty == 'other' else 'pass')


@pytest.mark.parametrize('indication,age,formulation,expected', [
    (N, 15, 'capsules', 'fail'), (N, 16, 'capsules', 'pass'),
    (N, 16, 'hetlioz_lq', 'fail'), (N, 3, 'hetlioz_lq', 'fail'),
    (S, 2, 'hetlioz_lq', 'fail'), (S, 3, 'hetlioz_lq', 'pass'),
    (S, 15, 'hetlioz_lq', 'pass'), (S, 15, 'capsules', 'fail'),
    (S, 16, 'hetlioz_lq', 'fail'), (S, 16, 'capsules', 'pass'),
    (S, 90, 'capsules', 'pass'), (S, 16, 'other', 'fail'),
])
def test_age_formulation(indication, age, formulation, expected):
    assert evaluate(pack(), dict(patient(indication), age_years=age, formulation=formulation)).decision == expected


@pytest.mark.parametrize('sighted,trial,expected', [
    (True, False, 'fail'), (True, True, 'pass'), (True, None, 'need_info'),
    (False, None, 'pass'), (False, False, 'pass'), (None, True, 'need_info'),
])
def test_light_therapy(sighted, trial, expected):
    assert evaluate(pack(), dict(patient(N), sighted_non24=sighted, light_therapy_trial_3_months=trial)).decision == expected


@pytest.mark.parametrize('indication', [N, S])
def test_ui(indication):
    fields = {f['key']: f for f in drug_detail('hetlioz')['fact_fields']}
    raw = {f: ('yes' if v is True else str(v)) for f,v in patient(indication).items()}
    assert evaluate(pack(), _coerce_patient(raw)).decision == 'pass'
    for c in pack()['criteria']:
        for f in c['required_facts']:
            assert fields[f]['type'] == 'select'
            if f not in ['age_years', 'formulation']:
                assert fields[f].get('when') == c.get('when')
    assert 'age_years' not in evaluate(pack(), {}).missing_facts


def test_metadata_catalog_notes():
    p = pack()
    assert p['drug']['generic_name'] == 'tasimelteon'
    assert p['source']['effective_date'] == '2022-05-01'
    assert p['encoding_status'] == 'partial'
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert (BASE / 'hetlioz.json').read_bytes() == (BASE / 'rule_packs/hetlioz.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['hetlioz'] == p and len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 106
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 92
    assert catalog['myqorzotm']['encoding_status'] == 'text_only'
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (106, 92)
    assert status['next_candidate'] == 'myqorzotm'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
    for text in ['without food', 'smoking', '3 months', '6 months', '14 day actigraphy', '60 days', 'last 30 days', '20mg', '158ml', '48ml', 'manual review']:
        assert text in ' '.join(p['notes'])
