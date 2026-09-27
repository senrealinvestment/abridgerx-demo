"""Kevzara: adult RA/PMR, gated therapy paths, lab thresholds and safety."""
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
PATHS = {
    'rheumatoid_arthritis': dict(ra_conventional_dmard_90d='trial_failure_gte_90d', ra_tnf_blocker_90d='trial_failure_gte_90d'),
    'polymyalgia_rheumatica': dict(pmr_eular_acr_consistent='consistent', pmr_steroid_history='prednisone_gte_20mg_gt_8wk'),
}
SAFETY = ['no_current_serious_active_infection', 'not_with_biologic_dmard_or_jak']
LABS = dict(baseline_anc='anc_gte_2000', baseline_ast_alt='ast_alt_lte_1_5x_uln', baseline_platelets='platelets_gte_150000')


def pack():
    return json.loads((BASE / 'kevzara.json').read_text())


def facts_for(indication):
    return dict(indication=indication, age_years=18, prescriber_specialty='rheumatologist_or_consult', **dict.fromkeys(SAFETY, True), **LABS, **PATHS[indication])


def test_metadata_and_closed_indications():
    p = pack()
    assert p['drug'] == dict(name='Kevzara', generic_name='sarilumab', therapeutic_class='biologics')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2023-06-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/p3uhkcex/5biii-kevzara_criteria_2023.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/5biii-kevzara_criteria_2023.pdf'
    assert 'inferred_required_facts' not in p and len(p['criteria']) == 12
    assert [o['value'] for o in p['fact_ui']['indication']['options']] == list(PATHS)
    for invalid in ['yes', 'no', 'unknown', True, False, 'other', 'plaque_psoriasis']:
        r = evaluate(p, dict(facts_for('rheumatoid_arthritis'), indication=invalid))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == ['indication_fda_labeled']
    assert p['alternatives'] == ['infliximab']
    assert 'kevzara' in json.loads((BASE / 'infliximab.json').read_text())['alternatives']
    assert p['max_units']['quantity'] is None and p['max_units']['days_supply'] is None
    for text in ['Version 1', '03/13/2023', '4/21/2023', '6/1/2023', 'EULAR/ACR', '3 months', '6 months', 'CDAI', 'SDAI', 'PAS', '200 mg (1.14 ml)', '14 days', 'manufacturer', 'nature of the failure', 'tuberculosis', 'HIV', 'hepatitis B', 'hepatitis C', 'Live vaccines']:
        assert text in ' '.join(p['notes'])


def test_age_boundary_both_indications():
    for indication in PATHS:
        for age in [0, 17, 17.99, 18, 65]:
            r = evaluate(pack(), dict(facts_for(indication), age_years=age))
            assert r.decision == ('pass' if age >= 18 else 'fail')
            if age < 18:
                assert [c['id'] for c in r.failed_clauses] == ['fda_labeled_age']


def test_required_facts_ra_steps_pmr_or_labs_and_safety():
    p = pack()
    for indication in PATHS:
        facts = facts_for(indication)
        assert evaluate(p, facts).decision == 'pass'
        assert evaluate(p, _coerce_patient({k: 'yes' if v is True else str(v) for k, v in facts.items()})).decision == 'pass'
        for key in facts:
            missing = dict(facts)
            del missing[key]
            r = evaluate(p, missing)
            assert r.decision == 'need_info' and r.missing_facts == [key], (key, r)
        for key in ['prescriber_specialty', *PATHS[indication], *LABS]:
            for option in p['fact_ui'][key]['options']:
                value = option['value']
                good = value == facts[key] or (key == 'pmr_steroid_history' and value == 'flare_while_tapering_gte_7_5mg_last_12wk')
                r = evaluate(p, dict(facts, **{key: value}))
                assert r.decision == ('pass' if good else 'fail'), (key, value, r)
                if not good:
                    assert [c['id'] for c in r.failed_clauses] == [key]
        for key in SAFETY:
            r = evaluate(p, dict(facts, **{key: False}))
            assert r.decision == 'fail' and [c['id'] for c in r.failed_clauses] == [key]


def test_ui_and_clause_when_gating():
    p = pack()
    fields = {f['key']: f for f in drug_detail('kevzara')['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert all(f['type'] == 'select' and f['options'] and not f.get('free_text') for f in fields.values())
    assert fields['age_years']['option_style'] == 'age_bands'
    assert [o['value'] for o in fields['age_years']['options']] == ['0', '18']
    for indication in PATHS:
        facts = facts_for(indication)
        assert {k for k, f in fields.items() if _when_applies(f.get('when'), facts)} == set(facts)
        stale = {k: 'none' for k in fields if k not in facts}
        assert evaluate(p, dict(facts, **stale)).decision == 'pass'
        for option in fields['age_years']['options']:
            r = evaluate(p, _coerce_patient(dict(facts, age_years=option['value'])))
            assert r.decision == ('pass' if option['value'] == '18' else 'fail')
    for clause in p['criteria']:
        if 'when' in clause:
            assert clause['when'] == fields[clause['id']]['when']
    assert set(evaluate(p, {}).missing_facts) == {'indication', 'age_years', 'prescriber_specialty', *LABS, *SAFETY}


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 44
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 154
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    for slug in ['kevzara', 'infliximab']:
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / f'rule_packs/{slug}.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 44 and status['encoding_text_only'] == 154
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'evkeeza'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
