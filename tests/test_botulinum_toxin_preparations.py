"""Botulinum toxin: all product/indication paths, boundaries and missing facts."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/alaska/parsed'
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _when_applies
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

SLUG = 'botulinum-toxin-preparations'
BRANCHES = {
    'overactive_bladder': dict(oab_moderate_severe_symptoms=True,
        behavioral_therapy_trials=True, able_willing_self_catheterization=True,
        bladder_prior_therapy='two_treatments_ge_60_days_inadequate'),
    'neurogenic_bladder_detrusor_overactivity': dict(detrusor_overactivity_symptoms=True,
        bladder_prior_therapy='two_treatments_ge_60_days_inadequate'),
    'chronic_migraine_prophylaxis': dict(chronic_headache_frequency_duration=True,
        two_migraine_prophylaxis_classes=True, headache_not_due_to_other_disorder=True,
        prescriber_specialty='neurologist'),
    'spasticity': dict(refractory_to_oral_medication=True),
    'upper_limb_spasticity_xeomin': dict(refractory_to_oral_medication=True),
    'cervical_dystonia': dict(cervical_dystonia_diagnosis=True,
        reduce_abnormal_head_position_and_neck_pain=True),
    'severe_axillary_hyperhidrosis': dict(severe_axillary_hyperhidrosis_despite_topicals=True,
        hdss_ge_3=True),
    'strabismus': dict(treated_for_strabismus=True),
    'blepharospasm_associated_with_dystonia': dict(eyelid_function_impairment_due_to_dystonia=True,
        prescriber_specialty='neurologist'),
    'chronic_sialorrhea': dict(sialorrhea_prior_therapy='failed_one_first_line'),
}
PATHS = [
    ('overactive_bladder','botox',18),
    ('neurogenic_bladder_detrusor_overactivity','botox',5),
    ('chronic_migraine_prophylaxis','botox',18),
    ('spasticity','botox',2), ('spasticity','dysport',2),
    ('upper_limb_spasticity_xeomin','xeomin',2),
    *[('cervical_dystonia',p,18) for p in ['botox','dysport','myobloc','xeomin']],
    ('severe_axillary_hyperhidrosis','botox',17), ('strabismus','botox',12),
    ('blepharospasm_associated_with_dystonia','botox',12),
    ('blepharospasm_associated_with_dystonia','xeomin',18),
    ('chronic_sialorrhea','xeomin',2), ('chronic_sialorrhea','myobloc',18),
]


def pack():
    return json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())


def facts(ind, product, age):
    f = dict(indication=ind, product=product, age_years=age,
        not_for_cosmetic_use=True, icd_code_present_on_request=True, **BRANCHES[ind])
    if ind == 'upper_limb_spasticity_xeomin' and age < 18:
        f['not_secondary_to_cerebral_palsy'] = True
    return f


@pytest.mark.parametrize('ind,product,age', PATHS)
def test_paths_boundaries_missing_denials_and_stale_facts(ind, product, age):
    p = pack()
    f = facts(ind, product, age)
    assert evaluate(p, f).decision == 'pass'
    result = evaluate(p, dict(f, age_years=age-1))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [ind+'_age']
    for key in f:
        missing = f.copy()
        del missing[key]
        result = evaluate(p, missing)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key], (key, result)
    for key, value in f.items():
        if value is True:
            result = evaluate(p, dict(f, **{key:False}))
            assert result.decision == 'fail', (key, result)
            assert result.citations == [p['source']['citation']]
    stale = {k:False for k, ui in p['fact_ui'].items()
             if not _when_applies(ui.get('when'), f)}
    assert evaluate(p, dict(f, **stale)).decision == 'pass'
    allowed = {pr for i,pr,a in PATHS if i == ind}
    for pr in ['botox','dysport','myobloc','xeomin','other',True]:
        if pr not in allowed:
            assert evaluate(p, dict(f, product=pr)).decision == 'fail'


def test_xeomin_adult_and_pediatric_cp_exception():
    f = facts('upper_limb_spasticity_xeomin','xeomin',18)
    assert evaluate(pack(), f).decision == 'pass'
    assert evaluate(pack(), dict(f, not_secondary_to_cerebral_palsy=False)).decision == 'pass'
    assert evaluate(pack(), dict(f, age_years=17)).missing_facts == ['not_secondary_to_cerebral_palsy']
    assert evaluate(pack(), dict(f, age_years=17, not_secondary_to_cerebral_palsy=False)).decision == 'fail'
    assert evaluate(pack(), dict(f, age_years=17, not_secondary_to_cerebral_palsy=True)).decision == 'pass'


@pytest.mark.parametrize('value', ['cosmetic','glabellar_lines','non_fda_medical','other',True,False])
def test_closed_indication(value):
    f = facts(*PATHS[0]); f['indication'] = value
    r = evaluate(pack(), f)
    assert r.decision == 'fail'
    assert [c['id'] for c in r.failed_clauses] == ['indication']


def test_select_alternatives_and_specialty():
    for ind, pr, age in PATHS:
        f = facts(ind, pr, age)
        for key in ['bladder_prior_therapy','sialorrhea_prior_therapy']:
            if key not in f:
                continue
            for o in pack()['fact_ui'][key]['options']:
                assert evaluate(pack(), dict(f, **{key:o['value']})).decision == (
                    'fail' if o['value']=='not_met' else 'pass')
        if 'prescriber_specialty' in f:
            for specialty in ['neurologist','ophthalmologist','other','neurologist_consult']:
                expected = specialty == 'neurologist' or (
                    ind == 'blepharospasm_associated_with_dystonia' and specialty == 'ophthalmologist')
                assert evaluate(pack(), dict(f,prescriber_specialty=specialty)).decision == ('pass' if expected else 'fail')


def test_ui_age_round_trip_gates_and_catalog():
    p = pack()
    fields = {f['key']:f for f in drug_detail(SLUG)['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert [o['value'] for o in fields['indication']['options']] == list(BRANCHES)
    assert [o['value'] for o in fields['product']['options']] == ['botox','dysport','myobloc','xeomin']
    for k, ui in p['fact_ui'].items():
        assert fields[k].get('when') == ui.get('when')
        assert fields[k]['type'] == 'select' and fields[k]['option_source'] == ('age_bands' if k == 'age_years' else 'fact_ui')
    assert set(evaluate(p, {}).missing_facts) == {'indication','not_for_cosmetic_use','icd_code_present_on_request'}
    for ind, pr, age in PATHS:
        f = facts(ind, pr, age)
        for option in fields['age_years']['options']:
            f.update(_coerce_patient({'age_years':option['value']}))
            assert evaluate(p, f).decision == ('pass' if f['age_years'] >= age else 'fail')
    assert p['encoding_status'] == 'partial' and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert p['source']['effective_date'] == '2024-06-01'
    assert p['drug']['therapeutic_class'] == 'neuromuscular'
    assert (BASE/f'{SLUG}.json').read_bytes() == (BASE/'rule_packs'/f'{SLUG}.json').read_bytes()
    c = load_rule_pack_catalog()
    assert c[SLUG] == p
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == c
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as stream:
        assert json.load(stream) == c
    assert len(c) == 198
    assert sum(v['encoding_status']=='partial' for v in c.values()) == 130
    assert sum(v['encoding_status']=='text_only' for v in c.values()) == 68
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert status['next_candidate'] == 'vykattm-xr'
    for suffix in ['md','json']:
        assert (BASE/f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent/f'ENCODING_STATUS.{suffix}').read_bytes()
    notes = ' '.join(p['notes'])
    for phrase in ['400 units','Black Box Warning','L38809','6 months','≥2 headache days','Version 5','Version 6']:
        assert phrase in notes
