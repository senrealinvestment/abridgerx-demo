"""Alaska Growth Hormone initial criteria: closed diagnoses and nested paths."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _when_applies
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
P = json.loads((BASE / 'rule_packs/somatropin.json').read_text())
INDICATIONS = ['pediatric_ghd', 'transition_ghd', 'adult_ghd', 'shox_deficiency', 'noonan_syndrome', 'turner_syndrome', 'prader_willi_syndrome', 'pediatric_ckd_growth_failure', 'sga_growth_failure']
SHARED = ['no_gh_contraindications_malignancy_retinopathy_critical_illness', 'not_for_iss_or_short_bowel', 'not_for_noncovered_diagnosis', 'not_for_athletic_recreational_social_body_mass', 'not_for_anti_aging', 'not_for_catabolic_illness_excluding_hiv', 'not_concurrent_increlex']
SPECIFIC = {
'pediatric_ghd': {'pediatric_ghd_open_epiphyses': True, 'pediatric_ghd_other_causes_ruled_out': True, 'pediatric_ghd_eligibility': 'growth_failure_additional_pituitary_deficiencies'},
 'transition_ghd': {'transition_ghd_stopped_ge_1_month_after_final_height': True, 'transition_ghd_reconfirmation': 'ge_3_pituitary_igf1_lt_2_5_percentile'},
 'adult_ghd': {'adult_ghd_stopped_ge_1_month': True, 'adult_ghd_eligibility': 'ge_3_pituitary_igf1_lt_2_5_percentile'},
 'shox_deficiency': {'shox_molecular_or_genetic_testing_confirmed': True},
 'noonan_syndrome': {'noonan_molecular_or_genetic_testing_confirmed': True},
 'turner_syndrome': {'turner_genetic_testing_confirmed': True},
 'prader_willi_syndrome': dict.fromkeys(['prader_willi_genetic_testing_confirmed', 'bmi_lt_35', 'no_severe_respiratory_impairment_or_untreated_severe_osa'], True),
 'pediatric_ckd_growth_failure': dict.fromkeys(['ckd_kidney_failure_gfr_lte_25_awaiting_transplant', 'ckd_optimal_nutrition', 'ckd_height_ge_2_sd_below_mean', 'ckd_growth_velocity_lt_10th_percentile', 'ckd_open_epiphyses', 'ckd_below_mid_parental_and_adult_height'], True),
 'sga_growth_failure': dict.fromkeys(['sga_birth_size_ge_2_sd_below_mean', 'sga_no_catch_up_before_age_4', 'sga_other_causes_ruled_out'], True),
}


def facts(ind):
    f = dict.fromkeys(SHARED, True) | {'indication': ind} | SPECIFIC[ind]
    if ind != 'shox_deficiency':
        f['gh_step_therapy_met'] = 'requesting_first_line_for_indication'
    return f


@pytest.mark.parametrize('ind', INDICATIONS)
def test_approval_denials_missing_and_gates(ind):
    f = facts(ind)
    assert evaluate(P, f).decision == 'pass'
    fields = {v['key']: v for v in drug_detail('somatropin')['fact_fields']}
    assert {k for k,v in fields.items() if _when_applies(v.get('when'), f)} == set(f)
    for key, value in f.items():
        missing = f.copy()
        del missing[key]
        result = evaluate(P, missing)
        assert result.decision == 'need_info' and result.missing_facts == [key]
        if key == 'indication':
            continue
        result = evaluate(P, f | {key: False if value is True else 'not_met'})
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [key]
        if value is True:
            for raw, outcome in [('yes', 'pass'), ('no', 'fail')]:
                assert evaluate(P, _coerce_patient(f | {key: raw})).decision == outcome
        else:
            for value in ['yes', 'unknown', True, 'unsupported']:
                assert evaluate(P, f | {key: value}).decision == 'fail'
            for option in P['fact_ui'][key]['options'][:-1]:
                assert evaluate(P, f | {key: option['value']}).decision == 'pass'
    stale = {k: False for k in P['fact_ui'] if k not in f}
    assert evaluate(P, f | stale).decision == 'pass'


@pytest.mark.parametrize('ind', ['iss', 'idiopathic_short_stature', 'short_bowel_syndrome', 'hiv_aids_wasting_cachexia', 'cystic_fibrosis', 'constitutional_delay', 'central_precocious_puberty', 'other', True, False])
def test_closed_indications(ind):
    result = evaluate(P, dict.fromkeys(SHARED, True) | {'indication': ind})
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication_covered']
    assert not result.missing_facts


def test_nested_paths_and_source_thresholds():
    options = P['fact_ui']['pediatric_ghd_eligibility']['options']
    assert {o['value'] for o in options} == {
        'growth_failure_additional_pituitary_deficiencies',
        'growth_failure_hypothalamic_pituitary_surgery_irradiation',
        'velocity_ge_2_sd_two_stim_tests', 'velocity_ge_2_sd_one_stim_test_low_igf1',
        'height_ge_2_sd_velocity_gt_1_sd_two_stim_tests',
        'height_ge_2_sd_velocity_gt_1_sd_one_stim_test_low_igf1', 'not_met'}
    assert len(P['fact_ui']['transition_ghd_reconfirmation']['options']) == 4
    assert len(P['fact_ui']['adult_ghd_eligibility']['options']) == 5
    for option in options[2:-1]:
        assert 'AND' in option['label']
        assert ('<10 ng/mL' if 'two_stim' in option['value'] else 'low IGF-1') in option['label']
    for option in options[4:-1]:
        assert 'Height ≥2 SD' in option['label'] and 'velocity >1 SD' in option['label']
    assert 'at least 6 months' in P['fact_ui']['gh_step_therapy_met']['options'][1]['label']
    assert 'shox_deficiency' not in P['fact_ui']['gh_step_therapy_met']['when']['in']


def test_metadata_ui_and_notes():
    assert P['encoding_status'] == 'partial'
    assert P['drug'] == dict(name='Somatropin', generic_name='somatropin', therapeutic_class='growth-hormones')
    assert P['source']['effective_date'] == '2026-01-01'
    assert P['source']['citation'].endswith('/o53pyou0/growthhormone_update_2026-004.pdf')
    assert P['source']['criteria_pdf'] == 'data/alaska/raw/growthhormone_update_2026-004.pdf'
    assert P['alternatives'] == [] and 'inferred_required_facts' not in P
    assert [o['value'] for o in P['fact_ui']['indication']['options']] == INDICATIONS
    assert len(P['criteria']) == 31
    assert set(P['fact_ui']) == {f for c in P['criteria'] for f in c['required_facts']}
    for clause in P['criteria']:
        ui = P['fact_ui'][clause['required_facts'][0]]
        assert ui['type'] == 'select'
        assert ui.get('when') == clause.get('when')
    notes = '\n'.join(P['notes'])
    for phrase in ['Version 3', '4/17/2026', '4/29/2016', '10/3/2016', '6 months', '12 months', 'Quantity limit: None', 'Reauthorization SHOX', 'Reauthorization Prader-Willi', 'Reauthorization CKD', 'Reauthorization SGA', 'Reauthorization pediatric GHD', 'Reauthorization transition and adult', 'Zorbtive', 'Skytrofa', 'Dosage Form/Strength', 'Second-Line']:
        assert phrase in notes


def test_catalog_mirrors_and_status():
    catalog = load_rule_pack_catalog()
    assert catalog['somatropin'] == P == json.loads((BASE / 'somatropin.json').read_text())
    assert catalog == json.loads((BASE / 'rule_packs_all.json').read_text())
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 187
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 11
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (187, 11)
    assert status['next_candidate'] == 'genotypes'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
