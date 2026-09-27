"""Briumvi Alaska Medicaid Version 1 eligibility, safety and catalog checks."""
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
    return json.loads((BASE / 'rule_packs/briumvi.json').read_text())


def facts(**updates):
    result = dict(indication=INDICATIONS[0], age_years=18,
                  prescriber_specialty='neurologist_or_ms_specialist_or_consult',
                  ms_dmt_step_two_12mo='trial_failure_intolerance_or_ci_two_or_more_12mo',
                  reproductive_status='not_of_reproductive_potential',
                  not_concurrent_ms_dmt=True, hepatitis_b_status='no_active_hepatitis_b')
    return dict(result, **updates)


def test_metadata_and_notes():
    p = pack()
    assert p['drug'] == dict(name='Briumvi', generic_name='ublituximab-xiiy',
                             therapeutic_class='ms-disease-modifying')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2023-06-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/lznp2jzr/5bi-briumvi_criteria_2023.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/5bi-briumvi_criteria_2023.pdf'
    assert p['max_units'] is None and p['alternatives'] == ['kesimpta', 'lemtrada', 'mavenclad', 'mayzent', 'ocrevus']
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 7
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '3/9/2023', '4/21/2023', '6/1/2023', '6 months',
                 '12 months', 'improvement or stabilization', '150 mg', '450 mg',
                 '2 weeks', '24 weeks', 'J3590', 'immunoglobulins', 'immunologist',
                 'active infection', 'live-attenuated', 'methylprednisolone',
                 'antihistamine', 'fetal harm', 'manual review']:
        assert text in ' '.join(p['notes']), text


def test_indications_age_and_reproductive_paths():
    for indication in INDICATIONS:
        for age in [18, 40, 80]:
            for reproductive in ['not_of_reproductive_potential',
                                 'not_pregnant_and_will_not_become_pregnant']:
                assert evaluate(pack(), facts(indication=indication, age_years=age,
                    reproductive_status=reproductive)).decision == 'pass'
        for age in [0, 17, 17.99]:
            assert_failure('fda_labeled_age', indication=indication, age_years=age)
    for value in ['yes', 'no', 'unknown', True, False, 'primary_progressive_ms', 'other']:
        assert_failure('indication_fda_labeled', indication=value)


def assert_failure(clause, **updates):
    result = evaluate(pack(), facts(**updates))
    assert result.decision == 'fail', result
    assert {c['id'] for c in result.failed_clauses} == {clause}, result
    assert result.citations


def test_approval_and_safety_denials():
    for fact, value in [('prescriber_specialty', 'none'), ('ms_dmt_step_two_12mo', 'none'),
                        ('reproductive_status', 'pregnant_or_may_become_pregnant'),
                        ('not_concurrent_ms_dmt', False), ('hepatitis_b_status', 'active_hepatitis_b')]:
        assert_failure(fact, **{fact: value})
    for fact in facts():
        patient = facts()
        del patient[fact]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert fact in result.missing_facts


def test_selects_coercion_and_gating():
    p = pack()
    detail = drug_detail('briumvi')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    assert p['fact_ui']['age_years']['option_style'] == 'age_bands'
    raw = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
    assert _coerce_patient(raw) == facts()
    passes = dict(indication=set(INDICATIONS), age_years={'18'},
                  reproductive_status={'not_of_reproductive_potential', 'not_pregnant_and_will_not_become_pregnant'})
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
    for fact in ['reproductive_status', 'not_concurrent_ms_dmt', 'hepatitis_b_status']:
        assert 'when' not in p['fact_ui'][fact]


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 146
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 52
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'briumvi.json').read_bytes() == (BASE / 'rule_packs/briumvi.json').read_bytes()
    assert catalog['soliris']['encoding_status'] == 'partial'
    assert catalog['praluent']['encoding_status'] == 'partial'
    assert catalog['actiq']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 146 and status['encoding_text_only'] == 52
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert 'briumvi' in status['partial_slugs'] and status['next_candidate'] == 'diclegis-bonjesta'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('briumvi tests ok')
