"""Benlysta: closed SLE/LN paths, age/route coupling and gated criteria."""
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
SAFETY = ['not_concomitant_biologic_dmard_or_lupkynis', 'no_severe_active_cns_lupus']
PATHS = {
    'systemic_lupus_erythematosus': dict(prescriber_specialty_sle='rheum_immuno_nephro_neuro_derm_or_consult', sle_autoantibody='ana_and_or_anti_dsdna_positive', sle_standard_therapy='receiving_or_ci'),
    'lupus_nephritis': dict(prescriber_specialty_ln='nephrologist_or_rheumatologist_or_consult', ln_biopsy_class='isn_rps_class_iii_or_iv_alone_or_with_v', ln_standard_therapy='receiving_or_ci'),
}


def pack():
    return json.loads((BASE / 'benlysta.json').read_text())


def facts_for(indication):
    return dict(indication=indication, age_years=18, administration_route='iv_infusion', **dict.fromkeys(SAFETY, True), **PATHS[indication])


def test_metadata_and_closed_indications():
    p = pack()
    assert p['drug'] == dict(name='Benlysta', generic_name='belimumab', therapeutic_class='other')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2022-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/1vjp4ova/202209-benlysta_criteria_2022.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/202209-benlysta_criteria_2022.pdf'
    assert 'inferred_required_facts' not in p and len(p['criteria']) == 11
    assert [o['value'] for o in p['fact_ui']['indication']['options']] == list(PATHS)
    for invalid in ['yes', 'no', 'unknown', True, False, 'other', 'plaque_psoriasis']:
        r = evaluate(p, dict(facts_for('lupus_nephritis'), indication=invalid))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == ['indication_fda_labeled']
    assert p['alternatives'] == ['lupkynis']
    assert p['max_units']['quantity'] is None and p['max_units']['days_supply'] is None
    notes = ' '.join(p['notes'])
    for text in ['Version 2', '12/20/21', '11/1/22', '4 months', '12 months', 'disease improvement', '10 mg/kg', '8 injections', '4 injections', 'J0490', 'PML', 'premedication', 'depression', 'suicidality']:
        assert text in notes


def test_age_route_boundaries_and_invalid_route():
    p = pack()
    for indication in PATHS:
        for route in ['iv_infusion', 'subcutaneous']:
            for age in [0, 4, 4.99, 5, 6, 17, 17.99, 18, 65]:
                r = evaluate(p, dict(facts_for(indication), age_years=age, administration_route=route))
                expected = age >= 18 or (age >= 5 and route == 'iv_infusion')
                assert r.decision == ('pass' if expected else 'fail'), (indication, age, route, r)
                ids = {c['id'] for c in r.failed_clauses}
                assert ('fda_labeled_age' in ids) == (age < 5)
                assert ('age_route_appropriate' in ids) == (not expected)
        for invalid in ['oral', 'yes', 'unknown']:
            r = evaluate(p, dict(facts_for(indication), administration_route=invalid))
            assert r.decision == 'fail' and [c['id'] for c in r.failed_clauses] == ['age_route_appropriate']


def test_each_path_missing_facts_and_denials():
    p = pack()
    for indication in PATHS:
        facts = facts_for(indication)
        assert evaluate(p, facts).decision == 'pass'
        coerced = _coerce_patient({k: 'yes' if v is True else str(v) for k, v in facts.items()})
        assert evaluate(p, coerced).decision == 'pass'
        for key in facts:
            missing = dict(facts)
            del missing[key]
            r = evaluate(p, missing)
            assert r.decision == 'need_info' and r.missing_facts == [key], (key, r)
        for key in PATHS[indication]:
            for option in p['fact_ui'][key]['options']:
                r = evaluate(p, dict(facts, **{key: option['value']}))
                assert r.decision == ('pass' if option['value'] == facts[key] else 'fail')
                if r.decision == 'fail':
                    assert [c['id'] for c in r.failed_clauses] == [key]
        for key in SAFETY:
            r = evaluate(p, dict(facts, **{key: False}))
            assert r.decision == 'fail' and [c['id'] for c in r.failed_clauses] == [key]


def test_ui_and_clause_gates_and_age_options():
    p = pack()
    fields = {f['key']: f for f in drug_detail('benlysta')['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert all(f['type'] == 'select' and f['options'] and not f.get('free_text') for f in fields.values())
    assert fields['age_years']['option_style'] == 'age_bands'
    assert [o['value'] for o in fields['age_years']['options']] == ['0', '5', '18']
    for indication in PATHS:
        facts = facts_for(indication)
        assert {k for k, f in fields.items() if _when_applies(f.get('when'), facts)} == set(facts)
        stale = {k: 'none' for k in fields if k not in facts}
        assert evaluate(p, dict(facts, **stale)).decision == 'pass'
        for option in fields['age_years']['options']:
            for route in ['iv_infusion', 'subcutaneous']:
                submitted = dict(facts, age_years=option['value'], administration_route=route)
                r = evaluate(p, _coerce_patient(submitted))
                assert r.decision == ('pass' if option['value'] == '18' or (option['value'] == '5' and route == 'iv_infusion') else 'fail')
    for clause in p['criteria']:
        if 'when' in clause:
            assert clause['when'] == fields[clause['id']]['when']
    assert set(evaluate(p, {}).missing_facts) == {'indication', 'age_years', 'administration_route', *SAFETY}


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 134
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 64
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert (BASE / 'benlysta.json').read_bytes() == (BASE / 'rule_packs/benlysta.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 134 and status['encoding_text_only'] == 64
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'nexletol'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
