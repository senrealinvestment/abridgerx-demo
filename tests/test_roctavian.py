"""Roctavian Alaska Medicaid Version 1 eligibility and catalog regressions."""
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
GATED = {
    'factor_viii_level_severe', 'factor_viii_exposure_days_gt_150',
    'no_factor_viii_inhibitors_screen_within_2w_lt_0_6_bu',
    'no_preexisting_antibodies_aav5_fda_test',
    'hepatic_ultrasound_and_elastography_done', 'baseline_liver_labs_documented',
}


def pack():
    return json.loads((BASE / 'rule_packs/roctavian.json').read_text())


def facts(**updates):
    return dict(dict(
        indication='hemophilia_a_severe', age_years=18,
        prescriber_specialty='hematologist', factor_viii_level_severe='lt_1_iu_dl',
        factor_viii_exposure_days_gt_150=True,
        no_factor_viii_inhibitors_screen_within_2w_lt_0_6_bu='no_history_and_screen_lt_0_6_bu_within_2_weeks',
        no_preexisting_antibodies_aav5_fda_test=True,
        hepatic_ultrasound_and_elastography_done=True,
        baseline_liver_labs_documented=True, no_active_hepatitis_b_or_c=True,
        no_uncontrolled_hiv=True, no_hepatic_fibrosis_stage_3_4_or_cirrhosis=True,
        no_known_hypersensitivity_to_mannitol=True,
        no_prior_hemophilia_a_gene_therapy=True), **updates)


def assert_failure(clause, **updates):
    result = evaluate(pack(), facts(**updates))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {clause}
    assert result.citations == [pack()['source']['citation']]


def test_closed_indication_age_and_specialty():
    for specialty in ['hematologist', 'hematologist_consult']:
        for age in [18, 18.01, 80]:
            assert evaluate(pack(), facts(age_years=age, prescriber_specialty=specialty)).decision == 'pass'
    for value in ['yes', 'no', 'unknown', True, False, 'hemophilia_b_moderate_severe', 'hemophilia_a', 'other']:
        assert_failure('indication_fda_labeled', indication=value)
    for age in [0, 17, 17.99]:
        assert_failure('age_fda_labeled', age_years=age)
    assert_failure('prescriber_specialty', prescriber_specialty='other')


def test_strict_factor_and_inhibitor_thresholds():
    for value in ['ge_1_iu_dl_or_not_documented', 'gte_1_iu_dl', 'yes', 'no', 'unknown', True, False]:
        assert_failure('factor_viii_level_severe', factor_viii_level_severe=value)
    for value in ['history_or_screen_ge_0_6_bu_or_missing', 'no_history_and_screen_le_0_6_bu_within_2_weeks', 'yes', 'unknown', True]:
        assert_failure('no_factor_viii_inhibitors_screen_within_2w_lt_0_6_bu',
                       no_factor_viii_inhibitors_screen_within_2w_lt_0_6_bu=value)


@pytest.mark.parametrize('fact', [f for f, value in facts().items() if value is True])
def test_approval_attestations_and_explicit_denials(fact):
    # Denial 1 is failure of any approval clause; denials 2-6 are explicit exclusions.
    assert_failure(fact, **{fact: False})


@pytest.mark.parametrize('fact', facts())
@pytest.mark.parametrize('missing', [None, 'absent'])
def test_missing_needs_information(fact, missing):
    patient = facts()
    if missing == 'absent':
        del patient[fact]
    else:
        patient[fact] = None
    result = evaluate(pack(), patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


def test_when_gating_and_ui_options():
    fields = {f['key']: f for f in drug_detail('roctavian')['fact_fields']}
    assert set(fields) == set(facts())
    gate = {'fact': 'indication', 'in': ['hemophilia_a_severe']}
    assert {c['required_facts'][0] for c in pack()['criteria'] if c.get('when') == gate} == GATED
    for f in GATED:
        assert fields[f]['when'] == gate
    for indication in ['other', None]:
        patient = {k: v for k, v in facts(indication=indication).items() if k not in GATED}
        result = evaluate(pack(), patient)
        assert result.decision == ('fail' if indication else 'need_info')
        assert not GATED.intersection(result.missing_facts)
    assert [o['value'] for o in fields['indication']['options']] == ['hemophilia_a_severe']
    raw = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
    for fact, field in fields.items():
        assert field['type'] == 'select'
        for option in field['options']:
            value = option['value']
            good = value == raw[fact] or (fact == 'prescriber_specialty' and value == 'hematologist_consult')
            result = evaluate(pack(), _coerce_patient(dict(raw, **{fact: value})))
            assert result.decision == ('pass' if good else 'fail'), (fact, value)


def test_metadata_notes_catalog_and_mirrors():
    p = pack()
    assert p['drug'] == dict(name='Roctavian', generic_name='valoctocogene roxaparvovec-rvox', therapeutic_class='cell-and-gene-therapy')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2023-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/1xtnjrrz/roctavian_criteria_2023.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/roctavian_criteria_2023.pdf'
    assert p['alternatives'] == [] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 14
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '07/3/2023', '09/15/2023', '11/1/2023', '3 months',
                 'no reauthorization', 'one infusion per lifetime', 'J3590', 'weekly',
                 '26 weeks', 'five years', 'alpha-fetoprotein', 'corticosteroid', 'manual review']:
        assert text in ' '.join(p['notes'])
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 118
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 80
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'roctavian.json').read_bytes() == (BASE / 'rule_packs/roctavian.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (118, 80)
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'voyxact'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
