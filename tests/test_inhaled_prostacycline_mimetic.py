"""Tyvaso/Ventavis: product eligibility, RHC boundaries and independent PAH steps."""
import gzip
import itertools
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
SLUG = 'inhaled-prostacycline-mimetic'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
PAH = 'pulmonary_arterial_hypertension_who_group_1'
ILD = 'pulmonary_hypertension_ild_who_group_3'


def facts(indication=PAH, product='tyvaso'):
    f = dict(product=product, indication=indication,
             prescriber_specialty='cardiologist_or_pulmonologist_or_consult',
             rhc_confirmation='rhc_confirmed', baseline_6mwd='obtained',
             mean_pap_mmhg='ge30', pcwp_mmhg='le12', pvr_wood_units='ge4_lt6_25')
    if indication == PAH:
        f.update(age_to_fda_label='meets_label', who_functional_class='iii')
    else:
        f.update(age_years=18)
    return f


@pytest.mark.parametrize('indication,product,decision', [
    (PAH, 'tyvaso', 'pass'), (PAH, 'ventavis', 'pass'),
    (ILD, 'tyvaso', 'pass'), (ILD, 'ventavis', 'fail'),
])
def test_product_paths(indication, product, decision):
    assert evaluate(PACK, facts(indication, product)).decision == decision


@pytest.mark.parametrize('indication', [PAH, ILD])
def test_every_missing_active_fact(indication):
    f = facts(indication)
    for key in f:
        missing = f.copy()
        del missing[key]
        result = evaluate(PACK, missing)
        assert result.decision == 'need_info'
        assert set(result.missing_facts) == ({'who_functional_class', 'pde5_trial', 'other_oral_pah_trial'} if key == 'who_functional_class' else {key})
    for key in ['product', 'indication', 'prescriber_specialty', 'rhc_confirmation', 'baseline_6mwd']:
        for value in ['unknown', 'other', True, False]:
            assert evaluate(PACK, dict(f, **{key: value})).decision == 'fail'


@pytest.mark.parametrize('indication', [PAH, ILD])
def test_all_hemodynamic_bands(indication):
    # Representative values independently express each source boundary.
    pap = {'lt25': 24.99, 'ge25_lt30': 25, 'ge30': 30}
    wedge = {'le12': 12, 'gt12_le15': 15, 'gt15': 15.01}
    pvr = {'le3': 3, 'gt3_lt4': 3.01, 'ge4_lt6_25': 4, 'ge6_25': 6.25}
    for a, w, r in itertools.product(pap, wedge, pvr):
        if indication == PAH:
            ok = pap[a] >= 25 and wedge[w] <= 15 and pvr[r] > 3
        else:
            ok = pap[a] >= 30 and pvr[r] >= 4 and wedge[w] <= (12 if pvr[r] < 6.25 else 15)
        result = evaluate(PACK, dict(facts(indication), mean_pap_mmhg=a, pcwp_mmhg=w, pvr_wood_units=r))
        assert result.decision == ('pass' if ok else 'fail')
        assert result.citations
    for key in ['mean_pap_mmhg', 'pcwp_mmhg', 'pvr_wood_units']:
        assert evaluate(PACK, dict(facts(indication), **{key: 'unknown'})).decision == 'fail'


@pytest.mark.parametrize('product', ['tyvaso', 'ventavis'])
def test_functional_class_and_both_independent_steps(product):
    f = facts(product=product)
    for fc in ['iii', 'iv']:
        assert evaluate(PACK, dict(f, who_functional_class=fc)).decision == 'pass'
        assert evaluate(PACK, dict(f, who_functional_class=fc, pde5_trial='not_met', other_oral_pah_trial='not_met')).decision == 'pass'
    for a, b in itertools.product(['failed', 'contraindicated', 'not_met', 'intolerant'], repeat=2):
        result = evaluate(PACK, dict(f, who_functional_class='ii', pde5_trial=a, other_oral_pah_trial=b))
        assert result.decision == ('pass' if a in ['failed', 'contraindicated'] and b in ['failed', 'contraindicated'] else 'fail')
    for key in ['pde5_trial', 'other_oral_pah_trial']:
        trial = dict(f, who_functional_class='ii', pde5_trial='failed', other_oral_pah_trial='failed')
        del trial[key]
        assert evaluate(PACK, trial).missing_facts == [key]
    for fc in ['i', 'unknown']:
        assert evaluate(PACK, dict(f, who_functional_class=fc)).decision == 'fail'


def test_age_and_walk_exceptions_do_not_bypass_other_gates():
    for age in [0, 17.99, 18, 70]:
        assert evaluate(PACK, dict(facts(ILD), age_years=age)).decision == ('pass' if age >= 18 else 'fail')
    assert evaluate(PACK, dict(facts(), age_to_fda_label='not_met')).decision == 'fail'
    for indication in [PAH, ILD]:
        f = dict(facts(indication), baseline_6mwd='inappropriate_by_prescriber')
        assert evaluate(PACK, f).decision == 'pass'
        assert evaluate(PACK, dict(f, rhc_confirmation='not_confirmed')).decision == 'fail'
    # Stale facts from the other path cannot impose requirements or grant approval.
    assert evaluate(PACK, dict(facts(ILD), age_to_fda_label='not_met', who_functional_class='ii', pde5_trial='not_met')).decision == 'pass'
    assert evaluate(PACK, dict(facts(), age_years=0)).decision == 'pass'


def test_ui_and_metadata():
    fields = {f['key']: f for f in drug_detail(SLUG)['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    for indication in [PAH, ILD]:
        assert evaluate(PACK, _coerce_patient({k: str(v) for k, v in facts(indication).items()})).decision == 'pass'
    assert fields['age_years']['when'] == {'fact': 'indication', 'eq': ILD}
    assert fields['who_functional_class']['when'] == {'fact': 'indication', 'eq': PAH}
    assert any(c.get('when', {}).get('fact') == 'product' for c in PACK['criteria'])
    assert PACK['encoding_status'] == 'partial'
    assert PACK['drug']['therapeutic_class'] == 'prostacyclin-mimetic-inhaled'
    assert PACK['source']['effective_date'] == '2022-03-01'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and 'inferred_required_facts' not in PACK
    for phrase in ['hypotension', 'bleeding', 'anticoagulants', '3 months', '12 months', '34-day', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])


def test_catalog_and_mirrors():
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 184
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 14
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (184, 14)
        assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'h-pylori-kits'
        assert catalog[status['next_candidate']]['encoding_status'] == 'text_only'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
