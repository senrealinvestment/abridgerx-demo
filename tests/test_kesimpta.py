"""Kesimpta Alaska Medicaid Version 1 eligibility, safety and catalog checks."""
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
    return json.loads((BASE / 'rule_packs/kesimpta.json').read_text())


def facts(**updates):
    result = dict(indication=INDICATIONS[0], age_years=18,
                  prescriber_specialty='neurologist_or_ms_specialist_or_consult',
                  igg_monitoring_agreement='agrees_monitor_beginning_during_after',
                  pretherapy_vaccination_window='no_live_4wk_and_no_nonlive_2wk',
                  hepatitis_b_screen='screened_negative',
                  ms_dmt_step_one='trial_failure_one_same_indication',
                  not_concurrent_ms_or_immunosuppressive=True, no_active_infection=True)
    return dict(result, **updates)


def test_metadata_and_notes():
    p = pack()
    assert p['drug'] == dict(name='Kesimpta', generic_name='ofatumumab',
                             therapeutic_class='ms-disease-modifying')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2021-03-15'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/qkfoumhj/202101-kesimpta_criteria_2021.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/202101-kesimpta_criteria_2021.pdf'
    assert p['max_units'] is None and p['alternatives'] == ['briumvi', 'lemtrada', 'mavenclad', 'mayzent', 'ocrevus']
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 9
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '12/05/20', '1/15/21', '3/15/21', '3 months',
                 '12 months', '4 injections', '1 injection every 4 weeks',
                 'contraception', 'fetal risks', 'opportunistic infection',
                 'immune compromise', 'injection site reactions', 'manual review']:
        assert text in ' '.join(p['notes']), text


def test_indications_and_age():
    for indication in INDICATIONS:
        for age in [18, 40, 80]:
            assert evaluate(pack(), facts(indication=indication, age_years=age)).decision == 'pass'
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
    for fact, value in [('prescriber_specialty', 'none'), ('ms_dmt_step_one', 'none'),
                        ('igg_monitoring_agreement', 'does_not_agree'),
                        ('pretherapy_vaccination_window', 'vaccination_within_window_or_not_attested'),
                        ('hepatitis_b_screen', 'positive_or_not_screened'),
                        ('not_concurrent_ms_or_immunosuppressive', False),
                        ('no_active_infection', False)]:
        assert_failure(fact, **{fact: value})
    for fact in facts():
        patient = facts()
        del patient[fact]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert fact in result.missing_facts


def test_selects_coercion_and_gating():
    p = pack()
    detail = drug_detail('kesimpta')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    assert p['fact_ui']['age_years']['option_style'] == 'age_bands'
    raw = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
    assert _coerce_patient(raw) == facts()
    passes = dict(indication=set(INDICATIONS), age_years={'18'})
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
    for fact in ['not_concurrent_ms_or_immunosuppressive', 'no_active_infection']:
        assert 'when' not in p['fact_ui'][fact]


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 69
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 129
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'kesimpta.json').read_bytes() == (BASE / 'rule_packs/kesimpta.json').read_bytes()
    assert catalog['kesimpta']['alternatives'] == ['briumvi', 'lemtrada', 'mavenclad', 'mayzent', 'ocrevus']
    assert 'kesimpta' in catalog['briumvi']['alternatives']
    assert (BASE / 'briumvi.json').read_bytes() == (BASE / 'rule_packs/briumvi.json').read_bytes()
    assert catalog['soliris']['encoding_status'] == 'partial'
    assert catalog['praluent']['encoding_status'] == 'partial'
    assert catalog['actiq']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 69 and status['encoding_text_only'] == 129
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert 'kesimpta' in status['partial_slugs'] and status['next_candidate'] == 'ofev'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('kesimpta tests ok')
