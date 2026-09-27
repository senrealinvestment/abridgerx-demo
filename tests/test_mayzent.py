"""Mayzent Alaska Medicaid Version 2 eligibility, safety and catalog checks."""
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
INDICATIONS = ['clinically_isolated_syndrome', 'relapsing_remitting_ms',
               'active_secondary_progressive_ms']


def pack():
    return json.loads((BASE / 'rule_packs/mayzent.json').read_text())


def facts(**updates):
    result = dict(indication=INDICATIONS[0], age_years=18,
                  prescriber_specialty='neurologist_or_ms_specialist_or_consult',
                  baseline_ecg_cbc_lft_ophthalmic_appropriate='all_done_appropriate',
                  no_recent_major_cv_event_6mo='no_mi_ua_stroke_tia_decomp_hf_or_class_iii_iv_hf_in_6mo',
                  av_block_sss_status='no_mobitz_ii_third_degree_or_sss',
                  cyp2c9_genotype='not_star3_star3',
                  ms_dmt_step_two='trial_failure_two_ms_drugs',
                  baseline_skin_exam_done='conducted_prior_to_therapy',
                  not_concurrent_ms_dmt=True)
    return dict(result, **updates)


def test_metadata_and_notes():
    p = pack()
    assert p['drug'] == dict(name='Mayzent', generic_name='siponimod',
                             therapeutic_class='ms-disease-modifying')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2022-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/0nmew0ca/202209-mayzent_criteria_2022.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/202209-mayzent_criteria_2022.pdf'
    assert p['max_units'] is None and p['alternatives'] == ['briumvi', 'kesimpta', 'lemtrada', 'mavenclad', 'ocrevus']
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 10
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 2', '7/05/2019', '09/16/2022', '11/01/2022',
                 '3 months', '12 months', '120 tablets of 0.25 mg',
                 '30 tablets of 1 mg', '30 tablets of 2 mg', 'infection',
                 'uveitis', 'diabetes', 'bradyarrhythmia', '4 weeks',
                 'CYP2C9', 'CYP3A4', 'cutaneous malignancies', 'manual review']:
        assert text in ' '.join(p['notes']), text


def test_indications_and_age():
    for indication in INDICATIONS:
        for age in [18, 40, 80]:
            assert evaluate(pack(), facts(indication=indication, age_years=age)).decision == 'pass'
        for age in [0, 17, 17.99]:
            assert_failure('fda_labeled_age', indication=indication, age_years=age)
    for value in ['yes', 'no', 'unknown', True, False, 'primary_progressive_ms', 'secondary_progressive_ms', 'other']:
        assert_failure('indication_fda_labeled', indication=value)


def assert_failure(clause, **updates):
    result = evaluate(pack(), facts(**updates))
    assert result.decision == 'fail', result
    assert {c['id'] for c in result.failed_clauses} == {clause}, result
    assert result.citations


def test_approval_and_safety_denials():
    for fact, value in [('prescriber_specialty', 'none'), ('ms_dmt_step_two', 'none'),
                        ('baseline_ecg_cbc_lft_ophthalmic_appropriate', 'incomplete_or_not_appropriate'),
                        ('no_recent_major_cv_event_6mo', 'recent_event_or_not_attested'),
                        ('av_block_sss_status', 'has_condition_without_pacemaker_or_not_attested'),
                        ('cyp2c9_genotype', 'star3_star3_or_not_tested'),
                        ('baseline_skin_exam_done', 'not_conducted'),
                        ('not_concurrent_ms_dmt', False)]:
        assert_failure(fact, **{fact: value})
    for indication in INDICATIONS:
        assert evaluate(pack(), facts(indication=indication, av_block_sss_status='has_condition_with_functioning_pacemaker')).decision == 'pass'
    assert_failure('ms_dmt_step_two', ms_dmt_step_two='trial_failure_one_ms_drug')
    for fact in facts():
        patient = facts()
        del patient[fact]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert fact in result.missing_facts


def test_selects_coercion_and_gating():
    p = pack()
    detail = drug_detail('mayzent')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    assert p['fact_ui']['age_years']['option_style'] == 'age_bands'
    raw = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
    assert _coerce_patient(raw) == facts()
    passes = dict(indication=set(INDICATIONS), age_years={'18'},
                  av_block_sss_status={raw['av_block_sss_status'], 'has_condition_with_functioning_pacemaker'})
    for fact, field in fields.items():
        assert field['type'] == 'select'
        assert field['option_source'] == ('age_bands' if fact == 'age_years' else 'fact_ui')
        for option in field['options']:
            value = option['value']
            expected = 'pass' if value in passes.get(fact, {raw[fact]}) else 'fail'
            assert evaluate(p, _coerce_patient(dict(raw, **{fact: value}))).decision == expected
    for clause in p['criteria']:
        fact = clause['required_facts'][0]
        assert clause.get('when') == p['fact_ui'][fact].get('when')
    for fact in ['not_concurrent_ms_dmt', 'baseline_skin_exam_done']:
        assert 'when' not in p['fact_ui'][fact]


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 68
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 130
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'mayzent.json').read_bytes() == (BASE / 'rule_packs/mayzent.json').read_bytes()
    assert catalog['mayzent']['alternatives'] == ['briumvi', 'kesimpta', 'lemtrada', 'mavenclad', 'ocrevus']
    assert 'mayzent' in catalog['briumvi']['alternatives']
    assert (BASE / 'briumvi.json').read_bytes() == (BASE / 'rule_packs/briumvi.json').read_bytes()
    for slug in ['briumvi', 'kesimpta', 'lemtrada', 'mavenclad', 'ocrevus']:
        assert 'mayzent' in catalog[slug]['alternatives']
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / f'rule_packs/{slug}.json').read_bytes()
    for slug in ['actiq', 'andembry']:
        assert catalog[slug]['encoding_status'] == 'partial'
    assert catalog['soliris']['encoding_status'] == 'partial'
    assert catalog['praluent']['encoding_status'] == 'partial'
    assert catalog['actiq']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 68 and status['encoding_text_only'] == 130
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert 'mayzent' in status['partial_slugs'] and status['next_candidate'] == 'orkambi'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('mayzent tests ok')
