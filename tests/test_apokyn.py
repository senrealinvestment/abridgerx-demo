"""Apokyn/Kynmobi source criteria, closed controls and catalog regression."""
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


def pack():
    return json.loads((BASE / 'rule_packs/apokyn.json').read_text())


def facts(**changes):
    return dict(dict(indication='parkinsons_off_episodes', age_years=18,
                     prescriber_specialty='neurologist', concurrent_anti_parkinson_agent=True,
                     hypomobility_episode_type='end_of_dose_wearing_off',
                     not_concurrent_5ht3_antagonist=True), **changes)


@pytest.mark.parametrize('specialty', ['neurologist', 'neurologist_consult'])
@pytest.mark.parametrize('episode', ['end_of_dose_wearing_off', 'unpredictable_on_off', 'both_or_either_documented'])
def test_qualifying_paths(specialty, episode):
    assert evaluate(pack(), facts(prescriber_specialty=specialty, hypomobility_episode_type=episode)).decision == 'pass'


@pytest.mark.parametrize('fact,value,clause', [
    ('age_years', 17.9, 'minimum_age'), ('age_years', 0, 'minimum_age'),
    ('indication', 'parkinsons', 'indication_fda_labeled'),
    ('indication', 'yes', 'indication_fda_labeled'),
    ('indication', True, 'indication_fda_labeled'),
    ('prescriber_specialty', 'other', 'prescriber_specialty'),
    ('prescriber_specialty', 'yes', 'prescriber_specialty'),
    ('concurrent_anti_parkinson_agent', False, 'concurrent_anti_parkinson_agent'),
    ('hypomobility_episode_type', 'not_met', 'hypomobility_episode_type'),
    ('hypomobility_episode_type', 'yes', 'hypomobility_episode_type'),
    ('not_concurrent_5ht3_antagonist', False, 'not_concurrent_5ht3_antagonist'),
])
def test_failures(fact, value, clause):
    result = evaluate(pack(), facts(**{fact: value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [clause]


def test_missing_and_age_boundary():
    for age in [18, 65]:
        assert evaluate(pack(), facts(age_years=age)).decision == 'pass'
    for key in facts():
        patient = facts()
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
    assert set(evaluate(pack(), {}).missing_facts) == set(facts())


def test_ui_coercion():
    detail = drug_detail('apokyn')
    assert detail['can_evaluate'] and detail['criteria_text']['extracted_text']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        assert field['options'] == pack()['fact_ui'][key]['options']
    assert [o['value'] for o in fields['indication']['options']] == ['parkinsons_off_episodes']
    patient = facts(age_years='18', concurrent_anti_parkinson_agent='yes', not_concurrent_5ht3_antagonist='yes')
    assert evaluate(pack(), _coerce_patient(patient)).decision == 'pass'
    for key in ['concurrent_anti_parkinson_agent', 'not_concurrent_5ht3_antagonist']:
        assert evaluate(pack(), _coerce_patient(dict(patient, **{key: 'no'}))).decision == 'fail'


def test_metadata_and_manual_review():
    p = pack()
    assert p['drug'] == dict(name='Apokyn/Kynmobi', generic_name='apomorphine', therapeutic_class='parkinsons')
    assert p['source']['effective_date'] == '2020-11-20'
    assert p['encoding_status'] == 'partial' and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 6
    assert {c['predicate']['fact'] for c in p['criteria']} == set(facts())
    notes = ' '.join(p['notes'])
    for term in ['1/11//20', '2026-03-01', 'up to 3 months', 'up to 12 months',
                 '5 injections per day / 150 injections per month', '5 films per day / 150 films per month',
                 'hypotension', 'QTc', 'hyperpyrexia', 'Dopamine antagonists']:
        assert term in notes


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['apokyn'] == pack()
    assert (BASE / 'apokyn.json').read_bytes() == (BASE / 'rule_packs/apokyn.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 121
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 77
    assert catalog['cinryze']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (121, 77)
    assert status['next_candidate'] == 'sunosi'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
