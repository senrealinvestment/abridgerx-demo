"""Hemgenix Alaska Medicaid Version 1 eligibility and catalog regressions."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PATHS = ['on_factor_ix_prophylaxis', 'current_or_historical_life_threatening_hemorrhage',
         'repeated_serious_spontaneous_bleeding']


def pack():
    return json.loads((BASE / 'rule_packs/hemgenix.json').read_text())


def facts(**updates):
    return dict(dict(indication='hemophilia_b_moderate_severe', age_years=18,
                     hemophilia_b_clinical_eligibility=PATHS[0],
                     prescriber_specialty='hematologist',
                     factor_ix_level_moderate_severe='lte_2_percent_or_lt_2_iu_dl',
                     factor_ix_exposure_days_gt_150=True,
                     no_fix_ix_inhibitors_screen_within_2w_le_0_5_bu='no_history_and_screen_le_0_5_bu_within_2_weeks',
                     hepatic_ultrasound_and_elastography_done=True,
                     no_active_hepatitis_b_or_c=True, no_uncontrolled_hiv=True,
                     no_advanced_hepatic_impairment=True,
                     no_prior_hemophilia_b_gene_therapy=True), **updates)


def assert_failure(clause, **updates):
    result = evaluate(pack(), facts(**updates))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {clause}
    assert result.citations


def test_indication_clinical_paths_age_and_specialty():
    for path in PATHS:
        for specialty in ['hematologist', 'hematologist_consult']:
            for age in [18, 18.01, 80]:
                assert evaluate(pack(), facts(hemophilia_b_clinical_eligibility=path,
                    prescriber_specialty=specialty, age_years=age)).decision == 'pass'
    for value in ['yes', 'no', 'unknown', True, False, 'hemophilia_a', 'other']:
        assert_failure('indication_fda_labeled', indication=value)
    for age in [0, 17, 17.99]:
        assert_failure('age_fda_labeled', age_years=age)
    assert_failure('hemophilia_b_clinical_eligibility', hemophilia_b_clinical_eligibility='none')
    assert_failure('prescriber_specialty', prescriber_specialty='other')


def test_approval_denial_and_missing_facts():
    assert_failure('factor_ix_level_moderate_severe', factor_ix_level_moderate_severe='above_2_or_not_documented')
    assert_failure('no_fix_ix_inhibitors_screen_within_2w_le_0_5_bu',
        no_fix_ix_inhibitors_screen_within_2w_le_0_5_bu='history_or_screen_positive_or_missing')
    for fact, value in facts().items():
        if value is True:
            assert_failure(fact, **{fact: False})
        patient = facts()
        del patient[fact]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [fact]


def test_gated_clinical_select_and_every_ui_option():
    fields = {f['key']: f for f in drug_detail('hemgenix')['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == ['hemophilia_b_moderate_severe']
    gate = {'fact': 'indication', 'in': ['hemophilia_b_moderate_severe']}
    assert fields['hemophilia_b_clinical_eligibility']['when'] == gate
    clause = next(c for c in pack()['criteria'] if c['id'] == 'hemophilia_b_clinical_eligibility')
    assert clause['when'] == gate
    assert clause['predicate'] == dict(op='in', fact='hemophilia_b_clinical_eligibility', values=PATHS)
    patient = facts(indication='other')
    del patient['hemophilia_b_clinical_eligibility']
    result = evaluate(pack(), patient)
    assert result.decision == 'fail'
    assert 'hemophilia_b_clinical_eligibility' not in result.missing_facts
    raw = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
    passing = {'hemophilia_b_clinical_eligibility': set(PATHS),
               'prescriber_specialty': {'hematologist', 'hematologist_consult'}}
    for fact, field in fields.items():
        assert field['type'] == 'select'
        for option in field['options']:
            value = option['value']
            good = float(value) >= 18 if fact == 'age_years' else value in passing.get(fact, {raw[fact]})
            result = evaluate(pack(), _coerce_patient(dict(raw, **{fact: value})))
            assert result.decision == ('pass' if good else 'fail'), (fact, value)


def test_metadata_notes_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='Hemgenix', generic_name='etranacogene dezaparvovec-drlb', therapeutic_class='cell-and-gene-therapy')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2023-06-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/pyydcag1/5bii-hemgenix_criteria_2023.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/5bii-hemgenix_criteria_2023.pdf'
    assert p['alternatives'] == ['beqvez-tm'] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 12
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '1/25/2023', '4/21/2023', '6/1/2023', '3 months',
                 'no reauthorization', 'one infusion per lifetime', 'J3590', 'weekly',
                 'five years', 'alpha-fetoprotein', 'manual review']:
        assert text in ' '.join(p['notes'])
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 156
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 42
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'hemgenix.json').read_bytes() == (BASE / 'rule_packs/hemgenix.json').read_bytes()
    assert catalog['beqvez-tm']['encoding_status'] == 'partial'
    assert catalog['beqvez-tm']['alternatives'] == ['hemgenix']
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 156 and status['encoding_text_only'] == 42
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'reclast'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


def test_no_aav_antibody_requirement():
    antibody = 'no_neutralizing_antibodies_aavrh74var_fda_test'
    assert 'aavrh74var' not in json.dumps(pack()).lower()
    for extra in [{}, {antibody: False}, {antibody: True}]:
        assert evaluate(pack(), facts(**extra)).decision == 'pass'
