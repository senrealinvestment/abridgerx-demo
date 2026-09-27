"""Alaska Zolgensma Version 1 eligibility, UI and catalog regression checks."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _eval_predicate, _missing_in_predicate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'


def pack():
    return json.loads((BASE / 'rule_packs/zolgensma.json').read_text())


def facts(**updates):
    return dict(dict(indication='spinal_muscular_atrophy', age_years=1,
                     prescriber_specialty='pediatric_neurologist_or_consult',
                     smn1_mutation='homozygous_deletion_or_mutation_smn1',
                     anti_aav9_titer='lte_1_to_50', not_concomitant_sma_therapy=True,
                     baseline_lft_platelet_troponin_i_within_30d_lt_2x_uln='all_done_within_30d_lt_2x_uln',
                     no_prior_zolgensma=True, not_advanced_sma='not_advanced',
                     no_active_unresolved_infection=True), **updates)


def assert_failure(clause, **updates):
    result = evaluate(pack(), facts(**updates))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {clause}
    assert result.citations


def test_indication_age_and_genetics():
    for mutation in ['homozygous_deletion_or_mutation_smn1', 'compound_heterozygous_mutation_smn1']:
        for age in [0, 1, 1.99]:
            assert evaluate(pack(), facts(age_years=age, smn1_mutation=mutation)).decision == 'pass'
    for age in [2, 2.01, 10, 80]:
        assert_failure('age_fda_labeled', age_years=age)
    for indication in ['yes', 'no', 'unknown', True, False, 'other', 'dmd_ambulatory_age_4_to_5']:
        assert_failure('indication_fda_labeled', indication=indication)


def test_each_exclusion_and_missing_fact():
    failures = dict(prescriber_specialty='none', smn1_mutation='not_confirmed',
                    anti_aav9_titer='gt_1_to_50_or_not_documented',
                    not_concomitant_sma_therapy=False,
                    baseline_lft_platelet_troponin_i_within_30d_lt_2x_uln='incomplete_or_elevated',
                    no_prior_zolgensma=False, not_advanced_sma='advanced_complete_paralysis_vent_trach',
                    no_active_unresolved_infection=False)
    for fact, value in failures.items():
        assert_failure(fact, **{fact: value})
    for fact in facts():
        patient = facts()
        del patient[fact]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [fact]


def test_ui_options():
    detail = drug_detail('zolgensma')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == ['spinal_muscular_atrophy']
    raw = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
    assert _coerce_patient(raw) == facts()
    passing = dict(age_years={'0'}, smn1_mutation={'homozygous_deletion_or_mutation_smn1', 'compound_heterozygous_mutation_smn1'})
    for fact, field in fields.items():
        assert field['type'] == 'select'
        assert field['option_source'] == ('age_bands' if fact == 'age_years' else 'fact_ui')
        for option in field['options']:
            value = option['value']
            expected = 'pass' if value in passing.get(fact, {raw[fact]}) else 'fail'
            assert evaluate(pack(), _coerce_patient(dict(raw, **{fact: value}))).decision == expected


def test_metadata_notes_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='Zolgensma', generic_name='onasemnogene abeparvovec-xioi', therapeutic_class='cell-and-gene-therapy')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2023-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/tngioada/zolgensma_criteria_2023.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/zolgensma_criteria_2023.pdf'
    assert p['alternatives'] == ['spinal-muscular-atrophy'] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 10
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '08/2/2023', '09/15/2023', '11/1/2023', '3 months',
                 'no reauthorization', 'one infusion per lifetime', '1.1×10^14', 'J3590',
                 'nusinersen', 'risdiplam', 'liver failure', '30-day', 'manual review']:
        assert text in ' '.join(p['notes'])
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 110
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 88
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'zolgensma.json').read_bytes() == (BASE / 'rule_packs/zolgensma.json').read_bytes()
    assert catalog['actiq']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 110 and status['encoding_text_only'] == 88
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'palforzia'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


def test_strict_lt_missing_and_composition():
    lt = dict(op='lt', fact='age_years', value=2)
    assert _eval_predicate(lt, {}) is None
    assert _missing_in_predicate(lt, {}) == ['age_years']
    for op in ['all', 'any']:
        predicate = dict(op=op, args=[lt])
        assert _eval_predicate(predicate, {'age_years': 1.99}) is True
        assert _eval_predicate(predicate, {'age_years': 2}) is False
        assert _missing_in_predicate(predicate, {}) == ['age_years']
