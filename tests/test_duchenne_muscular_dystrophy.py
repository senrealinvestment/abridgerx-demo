"""Alaska DMD ASO Version 1: closed eligibility, documentation and denial."""
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
SLUG = 'duchenne-muscular-dystrophy'
INDICATION = 'duchenne_muscular_dystrophy_exon_skipping'
ASSESSMENTS = [
    'six_minute_walk_test', 'north_star_ambulatory_assessment',
    'motor_function_measure',
    'brooke_ue_function_scale_le_5_and_fvc_ge_30_percent_predicted',
]
STEROIDS = ['receiving_concurrent_corticosteroids', 'corticosteroids_contraindicated_or_intolerant']
SPECIALTIES = ['neurologist_dmd_specialist', 'neurologist_dmd_specialist_consult']


def pack():
    return json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())


def facts(**updates):
    return dict(dict(
        indication=INDICATION,
        age_meets_fda_label_for_requested_product=True,
        prescriber_specialty=SPECIALTIES[0],
        dmd_mutation_amenable_to_target_exon_skipping_confirmed=True,
        baseline_renal_labs_cystatin_c_dipstick_upcr_submitted=True,
        baseline_muscle_strength_score_documented=ASSESSMENTS[0],
        concurrent_corticosteroids_or_contraindicated_intolerant=STEROIDS[0],
        current_weight_submitted=True,
        not_concomitant_other_exon_skipping_medication=True,
    ), **updates)


@pytest.mark.parametrize('assessment', ASSESSMENTS)
@pytest.mark.parametrize('steroids', STEROIDS)
@pytest.mark.parametrize('specialty', SPECIALTIES)
def test_all_approval_paths(assessment, steroids, specialty):
    assert evaluate(pack(), facts(
        baseline_muscle_strength_score_documented=assessment,
        concurrent_corticosteroids_or_contraindicated_intolerant=steroids,
        prescriber_specialty=specialty)).decision == 'pass'


@pytest.mark.parametrize('fact', facts())
def test_each_criterion_fails_independently(fact):
    value = False if facts()[fact] is True else 'not_met'
    result = evaluate(pack(), facts(**{fact: value}))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {
        'indication_fda_labeled' if fact == 'indication' else fact}
    assert result.citations == [pack()['source']['citation']]


@pytest.mark.parametrize('fact', facts())
@pytest.mark.parametrize('absent', [True, False])
def test_missing_fact(fact, absent):
    patient = facts()
    if absent:
        del patient[fact]
    else:
        patient[fact] = None
    result = evaluate(pack(), patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('indication', ['dmd', 'dmd_ambulatory_age_4_to_5', 'other', 'yes', True, False, None])
def test_closed_indication_and_gating(indication):
    result = evaluate(pack(), {'indication': indication})
    assert result.decision == ('need_info' if indication is None else 'fail')
    assert result.missing_facts == (['indication'] if indication is None else [])


@pytest.mark.parametrize('assessment', ['brooke_ue_function_scale_le_5', 'fvc_ge_30_percent_predicted', 'not_met'])
def test_brooke_and_fvc_must_be_combined(assessment):
    assert evaluate(pack(), facts(baseline_muscle_strength_score_documented=assessment)).decision == 'fail'


@pytest.mark.parametrize('specialty', ['neurologist', 'dmd_specialist', 'neuromuscular_specialist', 'primary_care'])
def test_requires_neurologist_specializing_in_dmd(specialty):
    assert evaluate(pack(), facts(prescriber_specialty=specialty)).decision == 'fail'


def test_authored_ui_and_coercion():
    p = pack()
    fields = {f['key']: f for f in drug_detail(SLUG)['fact_fields']}
    assert set(fields) == set(facts())
    gate = {'fact': 'indication', 'in': [INDICATION]}
    for clause in p['criteria']:
        fact = clause['required_facts'][0]
        if fact != 'indication':
            assert clause['when'] == fields[fact]['when'] == gate
        for option in fields[fact]['options']:
            raw = {k: 'yes' if v is True else v for k, v in facts().items()}
            raw[fact] = option['value']
            expected = option['value'] not in ['no', 'not_met', 'other']
            assert evaluate(p, _coerce_patient(raw)).decision == ('pass' if expected else 'fail')
    assert 'age_years' not in fields


def test_metadata_notes_catalog_and_mirrors():
    p = pack()
    assert p['encoding_status'] == 'partial'
    assert p['drug']['therapeutic_class'] == 'neuromuscular'
    assert p['source']['effective_date'] == '2022-06-01'
    source = json.loads((BASE / 'criteria_text' / f'{SLUG}.json').read_text())
    assert p['source']['citation'] == source['source_url']
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/' + source['source_file']
    assert len(p['criteria']) == 9
    assert p['alternatives'] == [] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    notes = ' '.join(p['notes'])
    for text in ['Version: 1', '2/26/2022', '4/15/2022', '6/1/2022',
                 'Exondys 51', 'Amondys 45', 'Vyondys 53', 'Viltepso',
                 'eteplirsen', 'casimersen', 'golodirsen', 'viltolarsen',
                 'confirmatory trial', '6 months', '12 months', 'stability',
                 '80 mg/kg', '30 mg/kg', 'J1426', 'J1427', 'J1428', 'J1429',
                 'elevidys', 'emflaza', 'manual review']:
        assert text in notes
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 73
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 125
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (73, 125)
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'strensiq'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
