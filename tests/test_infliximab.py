"""Infliximab class pack: Alaska indication branches, safety and UI boundaries."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _when_applies
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog, get_rule_pack

BASE = ROOT / 'data/alaska/parsed'
PEERS = ['entyvio', 'stelara', 'skyrizi', 'tremfya', 'zymfentra', 'bimzelx', 'kevzara']
PATHS = {
    'crohns_disease': (6, {'conventional_therapy_two': 'trial_failure_or_ci_two'}),
    'ulcerative_colitis': (6, {'conventional_therapy_two': 'trial_failure_or_ci_two'}),
    'rheumatoid_arthritis': (4, {'dmard_concurrent_two': 'trial_failure_or_ci_two_concurrent'}),
    'psoriatic_arthritis': (18, {'psa_conventional_two': 'trial_failure_or_ci_two'}),
    'ankylosing_spondylitis': (18, {'as_nsaid_step': 'trial_failure_or_ci_two_nsaids_3mo', 'as_dmard_step': 'trial_failure_or_ci_one_dmard_30d'}),
    'juvenile_idiopathic_arthritis': (4, {'jia_intraarticular_steroid': 'trial_failure_or_ci', 'jia_conventional_two': 'trial_failure_or_ci_two'}),
    'plaque_psoriasis': (18, {'pso_prior_therapy': 'trial_failure_or_ci'}),
    'hidradenitis_suppurativa': (None, {}),
}
BOOLS = ['tb_screened', 'hepatitis_b_or_c_screened', 'no_serious_infection', 'weight_submitted']


def pack():
    return json.loads((BASE / 'infliximab.json').read_text())


def facts_for(indication):
    age, steps = PATHS[indication]
    facts = dict(indication=indication, hf_dosing_safe='no_moderate_severe_hf', **dict.fromkeys(BOOLS, True), **steps)
    if age is not None:
        facts['age_years'] = age
    return facts


def test_metadata_closed_indications_and_gaps():
    p = pack()
    assert p['drug'] == dict(name='Infliximab', generic_name='infliximab', therapeutic_class='biologics')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2022-05-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/3nplwnjp/202203-infliximab_criteria_2022.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/202203-infliximab_criteria_2022.pdf'
    assert 'inferred_required_facts' not in p and len(p['criteria']) == 15
    assert [o['value'] for o in p['fact_ui']['indication']['options']] == list(PATHS)
    assert 'prescriber_specialty' not in p['fact_ui']
    assert p['max_units']['quantity'] is None and p['max_units']['days_supply'] is None
    for text in ['Version 1', '2/9/22', '3/18/22', '5/1/22', 'HS age not specified', 'no trial required',
                 '6 months', '12 months', 'stabilization', 'methotrexate', '10 mg/kg', 'every 4 weeks',
                 'J1745', 'Q5121', 'Q5103', 'Q5104', 'biosimilars', 'INFLIXIMAB (INJECTION)', 'non_preferred']:
        assert text in ' '.join(p['notes']), text
    for value in ['yes', 'no', 'unknown', True, False, 'other', 'psoriasis']:
        result = evaluate(p, dict(facts_for('hidradenitis_suppurativa'), indication=value))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['indication_fda_labeled']


def test_all_indication_paths_age_boundaries_and_missing_facts():
    p = pack()
    for indication, (minimum, steps) in PATHS.items():
        facts = facts_for(indication)
        assert evaluate(p, facts).decision == 'pass', indication
        raw = {k: 'yes' if v is True else str(v) for k, v in facts.items()}
        assert evaluate(p, _coerce_patient(raw)).decision == 'pass'
        for key in facts:
            missing = dict(facts)
            del missing[key]
            result = evaluate(p, missing)
            assert result.decision == 'need_info' and result.missing_facts == [key], (indication, key, result)
        if minimum is not None:
            for age in [0, minimum - .01, minimum, minimum + 1, 80]:
                result = evaluate(p, dict(facts, age_years=age))
                assert result.decision == ('pass' if age >= minimum else 'fail')
                if age < minimum:
                    assert [c['id'] for c in result.failed_clauses] == ['fda_labeled_age']
        else:
            assert 'age_years' not in facts and not steps
            assert evaluate(p, dict(facts, age_years=0)).decision == 'pass'


def test_wrong_steps_and_unrelated_facts():
    p = pack()
    all_steps = {k for _, steps in PATHS.values() for k in steps}
    for indication, (_, steps) in PATHS.items():
        facts = facts_for(indication)
        # Hidden stale values from another indication must not change the outcome.
        facts.update({k: 'none' for k in all_steps - steps.keys()})
        assert evaluate(p, facts).decision == 'pass'
        for key in steps:
            for wrong in ['none', 'yes', 'unknown', 'trial_failure', 'trial_failure_or_ci_one_dmard_30d' if key != 'as_dmard_step' else 'trial_failure_or_ci_two_nsaids_3mo']:
                result = evaluate(p, dict(facts, **{key: wrong}))
                assert result.decision == 'fail', (indication, key, wrong)
                assert [c['id'] for c in result.failed_clauses] == [key]


def test_shared_safety_and_heart_failure_options():
    p = pack()
    for indication in PATHS:
        facts = facts_for(indication)
        for key in BOOLS:
            result = evaluate(p, dict(facts, **{key: False}))
            assert result.decision == 'fail' and [c['id'] for c in result.failed_clauses] == [key]
        for value, expected in [('no_moderate_severe_hf', 'pass'), ('moderate_severe_hf_dose_lte_5mg_kg', 'pass'), ('moderate_severe_hf_dose_gt_5mg_kg', 'fail'), ('unknown', 'fail')]:
            result = evaluate(p, dict(facts, hf_dosing_safe=value))
            assert result.decision == expected
            if expected == 'fail':
                assert [c['id'] for c in result.failed_clauses] == ['hf_dosing_safe']


def test_ui_gates_and_age_four_band_round_trip():
    p = pack()
    fields = {f['key']: f for f in drug_detail('infliximab')['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert all(f['type'] == 'select' and f['options'] and not f.get('free_text') for f in fields.values())
    assert fields['age_years']['option_style'] == 'age_bands'
    assert [float(o['value']) for o in fields['age_years']['options']] == [0, .5, 1, 4, 6, 12, 18]
    for indication in PATHS:
        facts = facts_for(indication)
        visible = {k for k, f in fields.items() if _when_applies(f.get('when'), facts)}
        assert visible == set(facts)
        for c in p['criteria']:
            if 'when' in c:
                key = 'age_years' if c['id'] == 'fda_labeled_age' else c['id']
                assert c['when'] == fields[key]['when']
    for indication in ['rheumatoid_arthritis', 'juvenile_idiopathic_arthritis']:
        for option in fields['age_years']['options']:
            facts = facts_for(indication)
            facts.update(_coerce_patient({'age_years': option['value']}))
            assert evaluate(p, facts).decision == ('pass' if float(option['value']) >= 4 else 'fail')


def test_catalog_mirrors_and_alternatives():
    p = pack()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('infliximab') == ('infliximab', p)
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 183
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 15
    assert p['alternatives'] == PEERS
    for slug in ['infliximab'] + PEERS:
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / 'rule_packs' / f'{slug}.json').read_bytes()
        assert catalog[slug]['encoding_status'] == 'partial'
        if slug != 'infliximab':
            assert 'infliximab' in catalog[slug]['alternatives']
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 183 and status['encoding_text_only'] == 15
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'vitamin-d-50'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('infliximab tests ok')
