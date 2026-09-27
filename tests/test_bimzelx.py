"""Bimzelx: five closed adult indications, independent steps and gated UI."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _when_applies
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PEERS = ['skyrizi', 'tremfya', 'infliximab', 'stelara']
SAFETY = ['no_active_clinically_significant_infection', 'not_receiving_another_biologic', 'no_active_ibd']
PATHS = {
    'plaque_psoriasis': dict(prescriber_specialty_derm='dermatologist_or_consult', pso_severity='bsa_gte_3', pso_tnf_step='trial_failure_or_ci', pso_other_including_topical='trial_failure_or_ci_including_topical', weight_submitted=True, liver_labs_baseline_submitted=True),
    'psoriatic_arthritis': dict(prescriber_specialty_derm_or_rheum='dermatologist_or_rheumatologist_or_consult', caspar_status='caspar_gte_3_or_equivalent', psa_preferred_tnf='trial_failure_preferred_tnf_3mo', psa_conventional_3mo='trial_failure_or_ci_conventional_3mo', weight_submitted=True, liver_labs_baseline_submitted=True),
    'nr_axial_spa': dict(prescriber_specialty_rheum='rheumatologist_or_consult', nr_axspa_inflammation='crp_above_uln', nraxspa_nsaid_step='trial_failure_or_ci_two_nsaids_3mo', nraxspa_preferred_tnf='trial_failure_or_ci_preferred_tnf_3mo'),
    'ankylosing_spondylitis': dict(prescriber_specialty_rheum='rheumatologist_or_consult', basdai_status='basdai_gte_4_spinal_pain_gte_4', as_nsaid_step='trial_failure_or_ci_two_nsaids_3mo', as_preferred_tnf='trial_failure_or_ci_preferred_tnf_3mo'),
    'hidradenitis_suppurativa': dict(prescriber_specialty_derm='dermatologist_or_consult', hs_hurley_stage='hurley_stage_ii_or_iii', hs_oral_antibiotic_90d='trial_failure_or_ci_90d', hs_preferred_tnf_90d='trial_failure_or_ci_preferred_tnf_90d'),
}


def pack():
    return json.loads((BASE / 'bimzelx.json').read_text())


def facts_for(indication):
    return dict(indication=indication, age_years=18, **dict.fromkeys(SAFETY, True), **PATHS[indication])


def test_metadata_and_closed_indications():
    p = pack()
    assert p['drug'] == dict(name='Bimzelx', generic_name='bimekizumab-bkzx', therapeutic_class='biologics')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2024-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/t4uh1egh/bimzelx_criteria_update_2025.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/bimzelx_criteria_update_2025.pdf'
    assert 'inferred_required_facts' not in p and len(p['criteria']) == 25
    assert [o['value'] for o in p['fact_ui']['indication']['options']] == list(PATHS)
    for invalid in ['yes', 'no', 'unknown', True, False, 'crohns_disease', 'other']:
        r = evaluate(p, dict(facts_for('plaque_psoriasis'), indication=invalid))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == ['indication_fda_labeled']
    assert p['max_units']['quantity'] is None and p['max_units']['days_supply'] is None
    for text in ['Version 2', '07/15/2024', '9/20/2024', '11/1/2024', '11/21/2025', '3 months', '12 months', '320mg/28d', '160mg/28d', 'suicidal', 'latent TB', 'live vaccines', 'baseline PASI', 'contraindication']:
        assert text in ' '.join(p['notes']), text


def test_each_path_age_missing_facts_and_denials():
    p = pack()
    for indication in PATHS:
        facts = facts_for(indication)
        assert evaluate(p, facts).decision == 'pass', indication
        assert evaluate(p, _coerce_patient({k: 'yes' if v is True else str(v) for k, v in facts.items()})).decision == 'pass'
        for age in [0, 17, 17.99, 18, 65]:
            assert evaluate(p, dict(facts, age_years=age)).decision == ('pass' if age >= 18 else 'fail')
        for key in facts:
            missing = dict(facts); del missing[key]
            r = evaluate(p, missing)
            assert r.decision == 'need_info' and r.missing_facts == [key], (indication, key, r)
        for key in SAFETY + list(PATHS[indication]):
            r = evaluate(p, dict(facts, **{key: False if facts[key] is True else 'none'}))
            assert r.decision == 'fail' and [c['id'] for c in r.failed_clauses] == [key], (indication, key)


def test_every_severity_option_and_wrong_steps():
    p = pack()
    severities = {
        'plaque_psoriasis': ('pso_severity', {'bsa_gte_3', 'pasi_gte_10', 'concomitant_severe_psa'}),
        'psoriatic_arthritis': ('caspar_status', {'caspar_gte_3_or_equivalent'}),
        'nr_axial_spa': ('nr_axspa_inflammation', {'crp_above_uln', 'mri_sacroiliitis_no_structural_damage'}),
        'ankylosing_spondylitis': ('basdai_status', {'basdai_gte_4_spinal_pain_gte_4'}),
        'hidradenitis_suppurativa': ('hs_hurley_stage', {'hurley_stage_ii_or_iii'}),
    }
    for indication, (key, good) in severities.items():
        for option in p['fact_ui'][key]['options']:
            assert evaluate(p, dict(facts_for(indication), **{key: option['value']})).decision == ('pass' if option['value'] in good else 'fail')
        for key, value in PATHS[indication].items():
            if isinstance(value, str) and value.startswith('trial_'):
                for wrong in ['none', 'yes', 'unknown', 'trial_failure', 'trial_failure_or_ci_preferred_tnf_90d' if '90d' not in key else 'trial_failure_or_ci_preferred_tnf_3mo']:
                    assert evaluate(p, dict(facts_for(indication), **{key: wrong})).decision == 'fail', (key, wrong)
    # Each HS step alone is insufficient; both must attest to 90 days.
    hs = facts_for('hidradenitis_suppurativa')
    for key in ['hs_oral_antibiotic_90d', 'hs_preferred_tnf_90d']:
        assert evaluate(p, dict(hs, **{key: 'none'})).decision == 'fail'


def test_ui_and_clause_gates():
    p = pack()
    fields = {f['key']: f for f in drug_detail('bimzelx')['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert all(f['type'] == 'select' and f['options'] and not f.get('free_text') for f in fields.values())
    assert p['fact_ui']['age_years']['option_style'] == 'age_bands'
    assert 'options' not in p['fact_ui']['age_years']
    for indication in PATHS:
        facts = facts_for(indication)
        assert {k for k, f in fields.items() if _when_applies(f.get('when'), facts)} == set(facts)
        stale = {k: 'none' for k in fields if k not in facts}
        assert evaluate(p, dict(facts, **stale)).decision == 'pass'
    for clause in p['criteria']:
        if 'when' in clause:
            assert clause['when'] == fields[clause['id']]['when']
    for key in ['weight_submitted', 'liver_labs_baseline_submitted']:
        assert fields[key]['when']['in'] == ['plaque_psoriasis', 'psoriatic_arthritis']


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 30
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 168
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert pack()['alternatives'] == PEERS
    for slug in ['bimzelx'] + PEERS:
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / 'rule_packs' / f'{slug}.json').read_bytes()
        if slug != 'bimzelx':
            assert catalog[slug]['alternatives'].count('bimzelx') == 1
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 30 and status['encoding_text_only'] == 168
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'actiq'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('bimzelx tests ok')
