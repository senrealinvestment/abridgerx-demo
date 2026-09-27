"""OBOT no-PA alternatives, PA requirements, and catalog/UI integration."""
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
SLUG = 'oral-buprenorphine-based-medication-assisted-therapy-office-based-opioid-treatme'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
REQUIRED = ['mat_treatment_plan_on_record', 'regular_psychosocial_support', 'agreed_to_treatment_plan', 'prescriber_qualified_for_buprenorphine_mat', 'no_concomitant_other_opioids']


def patient():
    return dict(indication='opioid_dependence', age_years=16,
                new_mat_first_28_days=False, daily_buprenorphine_le_24mg=False,
                single_ingredient_buprenorphine=False, **dict.fromkeys(REQUIRED, True))


@pytest.mark.parametrize('arm', ['new_mat_first_28_days', 'daily_buprenorphine_le_24mg'])
def test_no_pa_arms_ignore_pa_requirements(arm):
    facts = dict(indication='opioid_dependence', age_years=16, **{arm: True})
    if arm == 'daily_buprenorphine_le_24mg':
        facts['single_ingredient_buprenorphine'] = False
    assert evaluate(PACK, facts).decision == 'pass'
    facts.update(dict.fromkeys(REQUIRED, False))
    assert evaluate(PACK, facts).decision == 'pass'
    facts['age_years'] = 15
    assert evaluate(PACK, facts).decision == 'fail'
    facts.update(age_years=16, indication='other')
    assert evaluate(PACK, facts).decision == 'fail'


@pytest.mark.parametrize('fact', REQUIRED)
@pytest.mark.parametrize('value', [False, None, 'absent'])
def test_pa_requirements(fact, value):
    facts = patient()
    if value == 'absent':
        facts.pop(fact)
    else:
        facts[fact] = value
    result = evaluate(PACK, facts)
    assert result.decision == ('fail' if value is False else 'need_info')
    if value is not False:
        assert fact in result.missing_facts


@pytest.mark.parametrize('single,pregnant,expected', [
    (False, None, 'pass'), (True, True, 'pass'), (True, False, 'fail'),
    (True, None, 'need_info'), (None, True, 'need_info'), (None, None, 'need_info')])
def test_product_restriction(single, pregnant, expected):
    facts = patient()
    facts.update(single_ingredient_buprenorphine=single, patient_pregnant_female=pregnant)
    assert evaluate(PACK, facts).decision == expected


def test_low_dose_does_not_exempt_single_ingredient():
    facts = patient()
    facts.update(daily_buprenorphine_le_24mg=True, single_ingredient_buprenorphine=True,
                 patient_pregnant_female=False)
    assert evaluate(PACK, facts).decision == 'fail'


@pytest.mark.parametrize('indication,expected', [(None, 'need_info'), ('other', 'fail'), ('pain', 'fail')])
def test_closed_indication_and_gating(indication, expected):
    result = evaluate(PACK, {'indication': indication})
    assert result.decision == expected
    assert result.missing_facts == (['indication'] if indication is None else [])


def test_missing_approval_arms_never_auto_pass():
    assert evaluate(PACK, {'indication': 'opioid_dependence', 'age_years': 16}).decision == 'need_info'
    facts = patient()
    facts['mat_treatment_plan_on_record'] = False
    facts.pop('new_mat_first_28_days')
    assert evaluate(PACK, facts).decision == 'need_info'


def test_ui_and_catalog():
    fields = {f['key']: f for f in drug_detail(SLUG)['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    for key in fields.keys() - {'indication'}:
        assert fields[key]['when'] == {'fact': 'indication', 'eq': 'opioid_dependence'}
    facts = _coerce_patient({'indication': 'opioid_dependence', 'age_years': '16', 'new_mat_first_28_days': 'yes'})
    assert evaluate(PACK, facts).decision == 'pass'
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE / 'rule_packs').glob('*.json')}
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 189
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 9
    assert catalog['2024-2025-season']['encoding_status'] == 'text_only'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (189, 9, '2024-2025-season')
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
    assert PACK['encoding_status'] == 'partial'
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for term in ['Version 2.1', '09/21/2018', '11/12/2018', '4/21/2023', '5/19/2023', '34-day', '22.8 mg/day', '12-month', 'six months', 'CMP', 'Regulatory authority', 'References']:
        assert term in notes
