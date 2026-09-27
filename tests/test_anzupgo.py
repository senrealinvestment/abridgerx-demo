"""Anzupgo: AK Version 1 eligibility, denial, UI and catalog integrity."""
import gzip
import json
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
IND = 'chronic_hand_eczema_moderate_severe'
CHRONIC = ['present_ge_3_months', 'ge_3_distinct_episodes_within_12_months_with_clearance_between']
STEP = ['failed_ge_1_month_medium_potency_tcs', 'contraindication_all_medium_potency_tcs']
DENIAL = 'not_combined_with_other_jak_or_potent_immunosuppressant'


def pack():
    return json.loads((BASE / 'rule_packs/anzupgo.json').read_text())


def facts(**updates):
    return dict({'indication': IND, 'age_years': 18, 'prescriber_specialty': 'dermatologist',
                 'che_chronicity': CHRONIC[0], 'medium_potency_tcs_step': STEP[0],
                 DENIAL: True}, **updates)


def test_all_approval_paths():
    for chronic, step, specialty, age in product(CHRONIC, STEP, ['allergist', 'dermatologist', 'immunologist'], [18, 80]):
        result = evaluate(pack(), facts(che_chronicity=chronic, medium_potency_tcs_step=step,
                                      prescriber_specialty=specialty, age_years=age))
        assert result.decision == 'pass', result


def test_rejected_values_and_age_boundary():
    cases = {
        'indication': ['yes', 'no', 'unknown', True, False, 'atopic_dermatitis', 'mild_hand_eczema'],
        'age_years': [0, 17, 17.99],
        'prescriber_specialty': ['primary_care', 'other', 'rheumatologist'],
        'che_chronicity': ['not_met', 'yes', True, 'ge_3_episodes_without_clearance'],
        'medium_potency_tcs_step': ['not_met', 'yes', True, 'failed_low_potency_tcs'],
        DENIAL: [False],
    }
    for key, values in cases.items():
        for value in values:
            result = evaluate(pack(), facts(**{key: value}))
            assert result.decision == 'fail', (key, value, result)
            expected = next(c['id'] for c in pack()['criteria'] if key in c['required_facts'])
            assert expected in {c['id'] for c in result.failed_clauses}


def test_missing_facts_need_info():
    for key in facts():
        patient = facts()
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
    result = evaluate(pack(), {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(facts())


def test_ui_and_coercion():
    detail = drug_detail('anzupgo')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    for field in fields.values():
        assert field['type'] == 'select' and field['options'] and not field.get('free_text')
    assert [o['value'] for o in fields['indication']['options']] == [IND]
    assert [o['value'] for o in fields['che_chronicity']['options']] == CHRONIC + ['not_met']
    assert [o['value'] for o in fields['medium_potency_tcs_step']['options']] == STEP + ['not_met']
    for answer, decision in [('yes', 'pass'), ('no', 'fail')]:
        assert evaluate(pack(), _coerce_patient(facts(age_years='18', **{DENIAL: answer}))).decision == decision


def test_source_notes_and_exact_predicates():
    p = pack()
    assert p['drug'] == {'name': 'Anzupgo', 'generic_name': 'delgocitinib', 'therapeutic_class': 'topical-jak'}
    assert p['source'] == {'payer': 'alaska_medicaid', 'list': 'Anzupgo Criteria',
        'effective_date': '2026-03-01', 'citation': 'https://health.alaska.gov/media/0agnjymc/anzupgo_criteria.pdf',
        'criteria_pdf': 'data/alaska/raw/anzupgo_criteria.pdf'}
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['alternatives'] == [] and 'inferred_required_facts' not in p
    predicates = {c['predicate']['fact']: c['predicate'] for c in p['criteria']}
    assert len(p['criteria']) == 6 and set(predicates) == set(facts())
    for key, values in [('indication', [IND]), ('prescriber_specialty', ['allergist', 'dermatologist', 'immunologist']), ('che_chronicity', CHRONIC), ('medium_potency_tcs_step', STEP)]:
        assert predicates[key] == {'fact': key, 'op': 'in', 'values': values}
    assert predicates[DENIAL] == {'fact': DENIAL, 'op': 'eq', 'value': True}
    assert predicates['age_years'] == {'fact': 'age_years', 'op': 'gte', 'value': 18}
    notes = ' '.join(p['notes'])
    for text in ['Version 1', '12/18/2025', '1/16/2026', '03/01/2026', '3 months', 'one year',
                 '60 grams per 30 days', 'Limitation of use', 'infection', 'basal cell carcinoma']:
        assert text in notes


def test_mirrors_bundles_counts_and_next_candidate():
    assert (BASE / 'anzupgo.json').read_bytes() == (BASE / 'rule_packs/anzupgo.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['anzupgo'] == pack()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 149
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 49
    assert catalog['cinryze']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 149 and status['encoding_text_only'] == 49
    assert status['next_candidate'] == 'invokana'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
