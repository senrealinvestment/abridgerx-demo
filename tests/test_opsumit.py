"""Opsumit source gates, alternate PDE5 paths, UI and catalog integrity."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, find_alternatives
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/opsumit.json').read_text())
FACTS = dict(indication='pulmonary_arterial_hypertension_who_group_1',
             prescriber_specialty='cardiologist_or_pulmonologist_or_consult',
             pah_confirmed_by_right_heart_catheterization='rhc_confirmed',
             currently_symptomatic='symptomatic', pde5_inhibitor_therapy='failed_after_60_days',
             pregnancy_attestation='not_pregnant_will_not_become_pregnant',
             baseline_lfts_submitted='submitted', baseline_hepatic_impairment='none_or_mild')


@pytest.mark.parametrize('key,allowed,denied', [
    ('indication', [FACTS['indication']], ['who_group_2_pah', 'who_group_1_pah', 'other']),
    ('prescriber_specialty', [FACTS['prescriber_specialty']], ['none']),
    ('pah_confirmed_by_right_heart_catheterization', ['rhc_confirmed'], ['not_confirmed']),
    ('currently_symptomatic', ['symptomatic'], ['not_symptomatic']),
    ('pde5_inhibitor_therapy', ['failed_after_60_days', 'currently_taking'], ['failed_before_60_days', 'not_met']),
    ('pregnancy_attestation', [FACTS['pregnancy_attestation']], ['pregnant_or_no_attestation']),
    ('baseline_lfts_submitted', ['submitted'], ['not_submitted']),
    ('baseline_hepatic_impairment', ['none_or_mild'], ['moderate', 'severe']),
])
def test_each_gate(key, allowed, denied):
    for value in allowed + denied + ['unknown', 'yes', 'no', True, False]:
        result = evaluate(PACK, dict(FACTS, **{key: value}))
        assert result.decision == ('pass' if value in allowed else 'fail')
        assert {c['id'] for c in result.failed_clauses} == (set() if value in allowed else {key})
        assert result.citations


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [False, True])
def test_missing(key, omit):
    patient = dict(FACTS, **{key: None})
    if omit:
        del patient[key]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('therapy', ['failed_after_60_days', 'currently_taking'])
def test_therapy_paths_do_not_bypass_lft_denial(therapy):
    assert evaluate(PACK, dict(FACTS, pde5_inhibitor_therapy=therapy)).decision == 'pass'
    for impairment in ['moderate', 'severe']:
        result = evaluate(PACK, dict(FACTS, pde5_inhibitor_therapy=therapy,
                                    baseline_hepatic_impairment=impairment))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['baseline_hepatic_impairment']


def test_ui_metadata_and_notes():
    detail = drug_detail('opsumit')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert len(fields['indication']['options']) == 1
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert evaluate(PACK, _coerce_patient(FACTS.copy())).decision == 'pass'
    assert all('when' not in c for c in PACK['criteria'])
    assert PACK['drug'] == dict(name='Opsumit', generic_name='macitentan', therapeutic_class='endothelin-receptor-antagonist')
    assert PACK['encoding_status'] == 'partial' and len(PACK['criteria']) == 8
    assert PACK['source']['effective_date'] == '2023-03-01'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and 'inferred_required_facts' not in PACK
    for text in ['pregnancy', 'PVOD', 'pulmonary edema', 'monitor LFTs', 'strong CYP3A4', 'moderate dual CYP3A4/CYP2C9', '6 months', '12 months', 'positive clinical response', '#30 10mg tablets per 30 days', 'manual review']:
        assert text in ' '.join(PACK['notes'])


def test_catalog_and_reciprocal_alternatives():
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert catalog['opsumit'] == PACK
    assert PACK['alternatives'] == ['uptravi']
    assert 'opsumit' in catalog['uptravi']['alternatives']
    assert catalog['uptravi']['encoding_status'] == 'partial'
    alternatives = find_alternatives(PACK, FACTS, catalog)
    assert len(alternatives) == 1
    assert alternatives[0]['verification'] == 'evaluate_need_info'
    assert (BASE / 'opsumit.json').read_bytes() == (BASE / 'rule_packs/opsumit.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 170
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 28
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (170, 28)
        assert status['next_candidate'] == 'dilaudid'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
