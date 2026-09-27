"""Alaska Skyclarys Version 1 eligibility, UI and catalog regressions."""
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


def pack():
    return json.loads((BASE / 'rule_packs/skyclarys.json').read_text())


def facts(**updates):
    return dict(dict(indication='friedreich_ataxia', age_years=16,
                     prescriber_specialty='neurologist_or_consult',
                     fxn_gene_mutation_confirmed='confirmed_by_genetic_testing',
                     clinically_symptomatic_fa='symptomatic', mfars_score='ge_20_and_le_80',
                     baseline_lft_bnp_hba1c_lvef_within_1yr='all_documented_within_1yr',
                     lvef_status='lvef_ge_40', hba1c_status='hba1c_le_11',
                     bnp_status='bnp_le_200'), **updates)


def assert_failure(clause, **updates):
    result = evaluate(pack(), facts(**updates))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {clause}
    assert result.citations


def test_closed_indication_and_age_boundary():
    for age in [16, 16.01, 18, 80]:
        assert evaluate(pack(), facts(age_years=age)).decision == 'pass'
    for age in [0, 15, 15.99]:
        assert_failure('age_fda_labeled', age_years=age)
    for indication in ['yes', 'no', 'unknown', True, False, 'other', 'spinal_muscular_atrophy']:
        assert_failure('indication_fda_labeled', indication=indication)


def test_each_gate_and_missing_fact():
    failures = dict(prescriber_specialty='none', fxn_gene_mutation_confirmed='not_confirmed',
                    clinically_symptomatic_fa='not_symptomatic',
                    mfars_score='outside_range_or_not_documented',
                    baseline_lft_bnp_hba1c_lvef_within_1yr='incomplete',
                    lvef_status='lvef_lt_40', hba1c_status='hba1c_gt_11', bnp_status='bnp_gt_200')
    for fact, value in failures.items():
        assert_failure(fact, **{fact: value})
        assert_failure(fact, **{fact: 'unknown'})
    for fact in facts():
        patient = facts()
        del patient[fact]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [fact]


def test_ui_options_and_inclusive_thresholds():
    detail = drug_detail('skyclarys')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == ['friedreich_ataxia']
    raw = {k: str(v) for k, v in facts().items()}
    assert _coerce_patient(raw) == facts()
    for fact, field in fields.items():
        assert field['type'] == 'select'
        assert field['option_source'] == ('age_bands' if fact == 'age_years' else 'fact_ui')
        for option in field['options']:
            value = option['value']
            expected = 'pass' if value == raw[fact] else 'fail'
            assert evaluate(pack(), _coerce_patient(dict(raw, **{fact: value}))).decision == expected
    for fact, label in dict(mfars_score='≥20 and ≤80', lvef_status='LVEF ≥40%',
                            hba1c_status='HbA1C ≤11%', bnp_status='BNP ≤200 pg/mL').items():
        assert fields[fact]['options'][0]['label'] == label


def test_metadata_notes_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='Skyclarys', generic_name='omaveloxolone', therapeutic_class='neurology')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2023-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/aznpmojd/skyclarys_criteria_2023.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/skyclarys_criteria_2023.pdf'
    assert p['alternatives'] == [] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 10
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '06/30/2023', '09/15/2023', '11/1/2023', '3 months',
                 '6 months', '102 capsules per 34 days', 'ALT', 'AST', 'bilirubin',
                 'every month for the first three months', 'periodically', 'CYP3A4',
                 'fetal harm', 'impaired coordination', 'diminished reflexes',
                 'frequent falls', 'skeletal muscle weakness', 'manual review']:
        assert text in ' '.join(p['notes'])
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 171
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 27
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'skyclarys.json').read_bytes() == (BASE / 'rule_packs/skyclarys.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 171 and status['encoding_text_only'] == 27
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'extended-release'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
