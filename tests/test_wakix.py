"""Wakix closed approval gates, independent therapy steps, denials and catalog."""
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
PACK = json.loads((BASE / 'rule_packs/wakix.json').read_text())
FACTS = dict(indication='excessive_daytime_sleepiness_with_narcolepsy', age_years=18,
             prescriber_specialty='sleep_specialist',
             baseline_sleepiness_validated_scale='documented_validated_scale',
             mslt_confirmation='standard_mslt_latency_le_8_and_soremps_ge_2',
             other_hypersomnolence_causes_ruled_out='ruled_out',
             daily_sleep_lapses_3_months='daily_for_ge_3_months',
             cns_stimulant_step='failed_ge_1_after_ge_30_days',
             wakefulness_promoting_step='failed_ge_1_after_ge_30_days',
             sleep_logs_last_30_days='submitted_last_30_days',
             severe_hepatic_impairment='absent', qt_history_or_risk='absent',
             qt_prolonging_drugs='absent', h1_receptor_antagonist='absent',
             sedative_hypnotic_agents='absent')


@pytest.mark.parametrize('key', [k for k in FACTS if k != 'age_years'])
def test_closed_gates(key):
    clause = next(c for c in PACK['criteria'] if c['id'] == key)
    allowed = clause['predicate']['values']
    for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['other', 'yes', 'no', True, False]:
        result = evaluate(PACK, dict(FACTS, **{key: value}))
        assert result.decision == ('pass' if value in allowed else 'fail')
        assert [c['id'] for c in result.failed_clauses] == ([] if value in allowed else [key])
        assert result.citations


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [False, True])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('age,decision', [(17, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


@pytest.mark.parametrize('stimulant', ['failed_ge_1_after_ge_30_days', 'contraindicated'])
@pytest.mark.parametrize('wakefulness', ['failed_ge_1_after_ge_30_days', 'contraindicated'])
def test_independent_steps(stimulant, wakefulness):
    facts = dict(FACTS, cns_stimulant_step=stimulant, wakefulness_promoting_step=wakefulness)
    assert evaluate(PACK, facts).decision == 'pass'
    for key in ['cns_stimulant_step', 'wakefulness_promoting_step']:
        assert evaluate(PACK, dict(facts, **{key: 'trial_under_30_days'})).decision == 'fail'
    assert evaluate(PACK, dict(facts, qt_prolonging_drugs='present')).decision == 'fail'


@pytest.mark.parametrize('invalid', ['latency_le_8_only', 'soremps_ge_2_only', 'nonstandard_mslt', 'latency_over_8', 'soremps_under_2'])
def test_mslt_requires_all_components(invalid):
    assert evaluate(PACK, dict(FACTS, mslt_confirmation=invalid)).decision == 'fail'


def test_ui_metadata_notes():
    detail = drug_detail('wakix')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert len(fields['indication']['options']) == 1
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert evaluate(PACK, _coerce_patient(dict(FACTS, age_years='18'))).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'pitolisant'
    assert PACK['source']['effective_date'] == '2021-05-24'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['CYP3A4', 'hormonal contraceptives', '21 days', 'CYP2D6', '17.8 mg once daily',
                 '3 months', '6 months', 'positive response', '53 × 8.9 mg', '60 × 17.8 mg',
                 'manual review', 'no management exception']:
        assert text in ' '.join(PACK['notes'])


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['wakix'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'wakix.json').read_bytes() == (BASE / 'rule_packs/wakix.json').read_bytes()
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 124
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 74
    assert catalog['orilissa']['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (124, 74)
        assert status['next_candidate'] == 'orilissa'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
