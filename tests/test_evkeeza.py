"""Alaska Evkeeza: HoFH gates, controlled inputs, and catalog integrity."""
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
    return json.loads((BASE / 'rule_packs/evkeeza.json').read_text())


def facts():
    return dict(
        indication='homozygous_familial_hypercholesterolemia', age_years=12,
        prescriber_specialty='cardiology',
        hofh_confirmation='genetic_two_mutant_alleles_ldlr_apob_pcsk9_or_ldlrap1',
        ezetimibe_with_max_atorvastatin_or_rosuvastatin_step_3mo='failed_3mo_adherent_ezetimibe_plus_max_atorva_or_rosuva',
        pcsk9_statin_ezetimibe_combo_step_3mo='failed_3mo_max_atorva_or_rosuva_plus_ezetimibe_plus_pcsk9_hofh',
        ldl_c_above_target_despite_pcsk9_statin_ezetimibe='ge_100_mg_dl',
        female_negative_pregnancy_test_and_contraception_counseled='done_or_not_applicable_male',
        baseline_ldl_tc_apob_non_hdl_documented=True,
        using_with_low_fat_or_heart_healthy_diet=True,
    )


def test_approval_paths_and_age_boundary():
    p = pack()
    for specialty in ('cardiology', 'lipidology', 'endocrinology',
                      'cardiology_consult', 'lipidology_consult', 'endocrinology_consult'):
        for confirmation in (
            'genetic_two_mutant_alleles_ldlr_apob_pcsk9_or_ldlrap1',
            'clinical_untreated_ldl_gt_500_or_treated_ge_300_with_early_manifest_or_both_parents_hefh',
        ):
            for ldl in ('ge_100_mg_dl', 'ge_70_mg_dl_with_clinical_ascvd'):
                for age in (0, 11.99, 12, 80):
                    result = evaluate(p, dict(facts(), prescriber_specialty=specialty,
                                             hofh_confirmation=confirmation,
                                             ldl_c_above_target_despite_pcsk9_statin_ezetimibe=ldl,
                                             age_years=age))
                    assert result.decision == ('pass' if age >= 12 else 'fail')
                    assert {c['id'] for c in result.failed_clauses} == (set() if age >= 12 else {'age_years'})
                    assert result.citations == [p['source']['citation']]
    assert evaluate(p, dict(facts(),
        ezetimibe_with_max_atorvastatin_or_rosuvastatin_step_3mo='statin_contraindicated',
        pcsk9_statin_ezetimibe_combo_step_3mo='contraindicated')).decision == 'pass'


def test_each_missing_fact_and_denial():
    p = pack()
    failures = dict(indication='heterozygous_familial_hypercholesterolemia', age_years=11,
        prescriber_specialty='other', hofh_confirmation='not_confirmed',
        ezetimibe_with_max_atorvastatin_or_rosuvastatin_step_3mo='not_met',
        pcsk9_statin_ezetimibe_combo_step_3mo='not_met',
        ldl_c_above_target_despite_pcsk9_statin_ezetimibe='not_met',
        female_negative_pregnancy_test_and_contraception_counseled='not_done',
        baseline_ldl_tc_apob_non_hdl_documented=False,
        using_with_low_fat_or_heart_healthy_diet=False)
    for key in facts():
        missing = facts()
        del missing[key]
        result = evaluate(p, missing)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
        result = evaluate(p, dict(facts(), **{key: failures[key]}))
        assert result.decision == 'fail'
        assert {c['id'] for c in result.failed_clauses} == {key}
    result = evaluate(p, {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(facts())
    for invalid in ('yes', 'no', 'unknown', 'other', True, False,
                    'heterozygous_familial_hypercholesterolemia', 'hypercholesterolemia'):
        assert evaluate(p, dict(facts(), indication=invalid)).decision == 'fail'


def test_controlled_ui_and_coercion():
    p = pack()
    fields = {f['key']: f for f in drug_detail('evkeeza')['fact_fields']}
    assert set(fields) == set(facts()) == set(p['fact_ui'])
    assert [o['value'] for o in fields['indication']['options']] == ['homozygous_familial_hypercholesterolemia']
    assert fields['age_years']['option_style'] == 'age_bands'
    assert fields['age_years']['options'] == [dict(value='0', label='Under 12 years'), dict(value='12', label='12+ years')]
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = _coerce_patient({key: option['value']})[key]
            result = evaluate(p, dict(facts(), **{key: value}))
            failing = value in ('not_met', 'not_confirmed', 'not_done', 'other') or value is False or (key == 'age_years' and value < 12)
            assert result.decision == ('fail' if failing else 'pass'), (key, value, result)


def test_metadata_catalog_and_manual_review_gaps():
    p = pack()
    assert len(p['criteria']) == 10
    assert p['drug'] == dict(name='Evkeeza', generic_name='evinacumab-dgnb', therapeutic_class='lipotropics')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2021-05-24'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/virpnhvu/202104-evkeeza_criteria_2021.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/202104-evkeeza_criteria_2021.pdf'
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    for c in p['criteria']:
        assert c['citation'] == p['source']['citation']
    for text in ('Version 1', '3/26/2021', '4/16/2021', '5/24/2021', 'ANGPTL3',
                 'HeFH', '3 months', '6 months', 'reduction from baseline',
                 '345 mg/2.3 mL', '2 vials per 28 days', '1,200 mg/8 mL',
                 '1 vial per 28 days', '1,890 mg', 'hypersensitivity', 'fetal harm',
                 'at least 5 months', 'manual review'):
        assert text in ' '.join(p['notes'])
    assert (BASE / 'evkeeza.json').read_bytes() == (BASE / 'rule_packs/evkeeza.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 126
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 72
    assert catalog['anzupgo']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 126 and status['encoding_text_only'] == 72
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'inhaled-prostacycline-mimetic'
    assert catalog[status['next_candidate']]['encoding_status'] == 'text_only'
    for ext in ('json', 'md'):
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
