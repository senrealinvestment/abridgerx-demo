"""Mavenclad Alaska Medicaid Version 1 eligibility, safety and catalog checks."""
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
INDICATIONS = ['relapsing_remitting_ms',
               'active_secondary_progressive_ms']


def pack():
    return json.loads((BASE / 'rule_packs/mavenclad.json').read_text())


def facts(**updates):
    result = dict(indication=INDICATIONS[0], age_years=18,
                  prescriber_specialty='neurologist_or_ms_specialist_or_consult',
                  cbc_and_lft_appropriate='cbc_and_lft_appropriate_for_treatment',
                  reproductive_contraception_counseling='counseled_effective_contraception_during_and_6mo_after_each_course',
                  ms_dmt_step_one='trial_failure_one_ms_drug',
                  no_current_malignancy=True,
                  no_hiv_or_active_chronic_infection='no_hiv_and_no_active_chronic_infection',
                  not_concurrent_ms_dmt=True, not_pregnant='not_pregnant')
    return dict(result, **updates)


def test_metadata_and_notes():
    p = pack()
    assert p['drug'] == dict(name='Mavenclad', generic_name='cladribine',
                             therapeutic_class='ms-disease-modifying')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2019-11-20'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/jj4jpm5c/20199mavenclad_criteria_approved_2019.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/20199mavenclad_criteria_approved_2019.pdf'
    assert p['max_units'] is None and p['alternatives'] == ['briumvi', 'kesimpta', 'lemtrada', 'mayzent', 'ocrevus']
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 10
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '7/05/2019', '9/20/2019', '11/20/2019',
                 '3 months', '12 months', '10 tablets per cycle', 'malignancy',
                 'fetal harm', 'infection risk', '4-6 weeks', 'manual review']:
        assert text in ' '.join(p['notes']), text


def test_indications_and_age():
    for indication in INDICATIONS:
        for age in [18, 40, 80]:
            assert evaluate(pack(), facts(indication=indication, age_years=age)).decision == 'pass'
        for age in [0, 17, 17.99]:
            assert_failure('fda_labeled_age', indication=indication, age_years=age)
    for value in ['yes', 'no', 'unknown', True, False, 'primary_progressive_ms', 'clinically_isolated_syndrome', 'secondary_progressive_ms', 'other']:
        assert_failure('indication_fda_labeled', indication=value)


def assert_failure(clause, **updates):
    result = evaluate(pack(), facts(**updates))
    assert result.decision == 'fail', result
    assert {c['id'] for c in result.failed_clauses} == {clause}, result
    assert result.citations


def test_approval_and_safety_denials():
    for fact, value in [('prescriber_specialty', 'none'), ('ms_dmt_step_one', 'none'),
                        ('cbc_and_lft_appropriate', 'not_done_or_not_appropriate'),
                        ('reproductive_contraception_counseling', 'not_counseled'),
                        ('no_current_malignancy', False),
                        ('no_hiv_or_active_chronic_infection', 'hiv_or_active_chronic_infection'),
                        ('not_concurrent_ms_dmt', False), ('not_pregnant', 'pregnant')]:
        assert_failure(fact, **{fact: value})
    for fact in facts():
        patient = facts()
        del patient[fact]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert fact in result.missing_facts


def test_selects_coercion_and_gating():
    p = pack()
    detail = drug_detail('mavenclad')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    assert p['fact_ui']['age_years']['option_style'] == 'age_bands'
    raw = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
    assert _coerce_patient(raw) == facts()
    passes = dict(indication=set(INDICATIONS), age_years={'18'},
                  reproductive_contraception_counseling={raw['reproductive_contraception_counseling'], 'not_applicable_or_counseled_n_a'})
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
    for fact in ['not_concurrent_ms_dmt', 'no_current_malignancy', 'no_hiv_or_active_chronic_infection', 'not_pregnant']:
        assert 'when' not in p['fact_ui'][fact]


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 173
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 25
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'mavenclad.json').read_bytes() == (BASE / 'rule_packs/mavenclad.json').read_bytes()
    assert catalog['mavenclad']['alternatives'] == ['briumvi', 'kesimpta', 'lemtrada', 'mayzent', 'ocrevus']
    assert 'mavenclad' in catalog['briumvi']['alternatives']
    assert (BASE / 'briumvi.json').read_bytes() == (BASE / 'rule_packs/briumvi.json').read_bytes()
    for slug in ['briumvi', 'kesimpta', 'lemtrada', 'mayzent', 'ocrevus']:
        assert 'mavenclad' in catalog[slug]['alternatives']
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / f'rule_packs/{slug}.json').read_bytes()
    for slug in ['actiq', 'andembry']:
        assert catalog[slug]['encoding_status'] == 'partial'
    assert catalog['soliris']['encoding_status'] == 'partial'
    assert catalog['praluent']['encoding_status'] == 'partial'
    assert catalog['actiq']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 173 and status['encoding_text_only'] == 25
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert 'mavenclad' in status['partial_slugs'] and status['next_candidate'] == 'oxycodone-hydrochloride-immediate-release'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('mavenclad tests ok')
