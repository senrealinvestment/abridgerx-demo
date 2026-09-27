"""Denosumab: product-specific Alaska criteria, boundaries and UI gates."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _when_applies
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PROLIA = [
    'prolia_breast_cancer_bone_mass',
    'prolia_glucocorticoid_induced_osteoporosis',
    'prolia_prostate_cancer_bone_mass',
    'prolia_male_osteoporosis',
    'prolia_postmenopausal_osteoporosis',
]
GCT = 'xgeva_giant_cell_tumor'
SRE = 'xgeva_sre_prevention'
HCM = 'xgeva_hypercalcemia_malignancy'
INDICATIONS = PROLIA + [GCT, SRE, HCM]
RISK = ['tscore_osteopenia_aromatase_inhibitor', 'tscore_osteopenia_adt',
        'tscore_osteopenia_fracture', 'frax_major_gte_20', 'frax_hip_gte_3', 'tscore_lte_minus_2_5']
BRANCHES = {
    **{i: dict(prolia_risk_documentation=RISK[-1],
               prolia_traditional_osteo_two='trial_failure_or_intolerant_two_including_bp') for i in PROLIA},
    GCT: dict(skeletally_mature='yes', tumor_resectability='unresectable_or_severe_morbidity_resection'),
    SRE: {},
    HCM: dict(albumin_corrected_calcium='gt_12_5_mg_dl', xgeva_bp_step='trial_failure_or_intolerant_one_bp'),
}


def pack():
    return json.loads((BASE / 'prolia.json').read_text())


def facts_for(indication):
    return dict(indication=indication, age_years=12 if indication == GCT else 18,
                not_concurrent_rankl_inhibitor=True,
                hypocalcemia_status='no_uncorrected_hypocalcemia', **BRANCHES[indication])


def test_metadata_closed_indications_and_notes():
    p = pack()
    assert p['drug'] == dict(name='Prolia', generic_name='denosumab', therapeutic_class='metabolic')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2022-03-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/g5gnbewr/202201-prolia_xgeva_criteria_2021.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/202201-prolia_xgeva_criteria_2021.pdf'
    assert len(p['criteria']) == 10 and 'inferred_required_facts' not in p
    assert [o['value'] for o in p['fact_ui']['indication']['options']] == INDICATIONS
    assert p['max_units']['quantity'] is None and p['max_units']['days_supply'] is None
    for invalid in ['yes', 'no', 'unknown', True, False, 'other', 'osteoporosis']:
        r = evaluate(p, dict(facts_for(SRE), indication=invalid))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == ['indication_fda_labeled']
    for text in ['Version 1', '12/16/21', '1/21/22', '3/1/22', '6 months', '12 months',
                 'stabilization', '60 mg', '4 vials per 28 days', '1 vial monthly', 'J0897',
                 'Source ambiguity', 'prolia_pi.pdf', 'xgeva_pi.pdf']:
        assert text in ' '.join(p['notes'])


@pytest.mark.parametrize('indication', INDICATIONS)
def test_age_boundaries_missing_facts_and_ui(indication):
    p = pack()
    facts = facts_for(indication)
    minimum = facts['age_years']
    for age in [0, minimum - .01, minimum, 18, 90]:
        r = evaluate(p, dict(facts, age_years=age))
        assert r.decision == ('pass' if age >= minimum else 'fail')
        if age < minimum:
            assert [c['id'] for c in r.failed_clauses] == ['fda_labeled_age']
    for key in facts:
        missing = dict(facts)
        del missing[key]
        r = evaluate(p, missing)
        assert r.decision == 'need_info' and r.missing_facts == [key]
    raw = {k: 'yes' if v is True else str(v) for k, v in facts.items()}
    assert evaluate(p, _coerce_patient(raw)).decision == 'pass'
    fields = {f['key']: f for f in drug_detail('prolia')['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert all(f['type'] == 'select' and f['options'] and not f.get('free_text') for f in fields.values())
    assert fields['age_years']['option_style'] == 'age_bands'
    assert [o['value'] for o in fields['age_years']['options']] == ['0', '12', '18']
    assert {k for k, f in fields.items() if _when_applies(f.get('when'), facts)} == set(facts)
    for c in p['criteria']:
        if 'when' in c:
            key = 'age_years' if c['id'] == 'fda_labeled_age' else c['id']
            assert fields[key]['when'] == c['when']
    # Hidden stale answers from other indication paths cannot deny this path.
    unrelated = {k for branch in BRANCHES.values() for k in branch} - BRANCHES[indication].keys()
    assert evaluate(p, dict(facts, **dict.fromkeys(unrelated, 'none'))).decision == 'pass'


@pytest.mark.parametrize('indication', PROLIA)
@pytest.mark.parametrize('risk', RISK)
def test_all_prolia_risk_branches(indication, risk):
    assert evaluate(pack(), dict(facts_for(indication), prolia_risk_documentation=risk)).decision == 'pass'


@pytest.mark.parametrize('indication,key,value', [
    (PROLIA[0], 'prolia_risk_documentation', 'none'),
    (PROLIA[0], 'prolia_traditional_osteo_two', 'none'),
    (PROLIA[0], 'prolia_traditional_osteo_two', 'trial_failure_or_intolerant_one_bp'),
    (PROLIA[0], 'prolia_traditional_osteo_two', 'two_without_bisphosphonate'),
    (GCT, 'skeletally_mature', 'no'),
    (GCT, 'skeletally_mature', False),
    (GCT, 'tumor_resectability', 'resectable_without_severe_morbidity'),
    (HCM, 'albumin_corrected_calcium', 'lte_12_5_or_not_documented'),
    (HCM, 'xgeva_bp_step', 'none'),
])
def test_branch_denials(indication, key, value):
    r = evaluate(pack(), dict(facts_for(indication), **{key: value}))
    assert r.decision == 'fail' and [c['id'] for c in r.failed_clauses] == [key]


@pytest.mark.parametrize('indication', INDICATIONS)
@pytest.mark.parametrize('key,value', [('not_concurrent_rankl_inhibitor', False),
                                       ('hypocalcemia_status', 'uncorrected_hypocalcemia')])
def test_shared_denials(indication, key, value):
    r = evaluate(pack(), dict(facts_for(indication), **{key: value}))
    assert r.decision == 'fail' and [c['id'] for c in r.failed_clauses] == [key]


def test_sre_has_no_invented_step():
    facts = facts_for(SRE)
    assert not BRANCHES[SRE]
    assert evaluate(pack(), facts).decision == 'pass'
    assert evaluate(pack(), dict(facts, xgeva_bp_step='none', albumin_corrected_calcium='lte_12_5_or_not_documented')).decision == 'pass'


def test_catalog_mirrors_and_bidirectional_alternatives():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 121
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 77
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    for slug, peer in [('prolia', 'evenity'), ('evenity', 'prolia')]:
        assert peer in catalog[slug]['alternatives']
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / f'rule_packs/{slug}.json').read_bytes()
    assert catalog['actiq']['encoding_status'] == 'partial'
    assert 'xgeva' not in catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 121 and status['encoding_text_only'] == 77
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'sunosi'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
    assert 'Biologics batch exhausted:' in (BASE / 'ENCODING_STATUS.md').read_text()
