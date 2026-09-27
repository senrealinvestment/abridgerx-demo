"""VMAT2 product/indication paths, threshold boundaries, exclusions and catalog."""
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
PACK = json.loads((BASE/'rule_packs/vesicular-monoamine.json').read_text())
PRODUCTS = ['austedo', 'austedo_xr', 'ingrezza', 'xenazine']
HD = 'huntington_chorea'
TD = 'moderate_severe_tardive_dyskinesia'
PATHS = [(p, i) for p in PRODUCTS for i in [HD, TD] if p != 'xenazine' or i == HD]


def facts(product, indication):
    f = dict(product=product, indication=indication, age_years=18,
             prescriber_specialty='neurology', concurrent_vmat2=False,
             concurrent_maoi=False, concurrent_reserpine=False)
    if product != 'ingrezza':
        f['significant_hepatic_impairment'] = False
    if product == 'xenazine':
        f['generic_tetrabenazine_manufacturers_failed'] = 2
    if indication == HD:
        f.update(suicidal=False, untreated_or_inadequately_treated_depression=False)
    else:
        f.update(td_causing_medications_addressed='reduced', baseline_aims=8,
                 aims_lines_1_7_max_score=3)
    return f


@pytest.mark.parametrize('product,indication', PATHS)
def test_paths_and_missing(product, indication):
    f = facts(product, indication)
    result = evaluate(PACK, f)
    assert result.decision == 'pass'
    assert result.citations == [PACK['source']['citation']]
    for key in f:
        for omit in [True, False]:
            incomplete = dict(f, **{key: None})
            if omit:
                del incomplete[key]
            result = evaluate(PACK, incomplete)
            assert result.decision == 'need_info', (key, result)
            assert key in result.missing_facts


@pytest.mark.parametrize('product,indication', PATHS)
def test_each_applicable_gate(product, indication):
    f = facts(product, indication)
    bad = dict(age_years=17.99, prescriber_specialty='other', product='other', indication='other',
               concurrent_vmat2=True, concurrent_maoi=True, concurrent_reserpine=True,
               significant_hepatic_impairment=True, suicidal=True,
               untreated_or_inadequately_treated_depression=True,
               generic_tetrabenazine_manufacturers_failed=1,
               td_causing_medications_addressed='not_addressed', baseline_aims=7.99,
               aims_lines_1_7_max_score=2.99)
    for key in f:
        assert evaluate(PACK, dict(f, **{key: bad[key]})).decision == 'fail', key


@pytest.mark.parametrize('product', PRODUCTS[:3])
@pytest.mark.parametrize('addressed', ['reduced', 'discontinued', 'clinical_rationale_not_possible'])
def test_td_alternatives(product, addressed):
    f = facts(product, TD)
    f.update(prescriber_specialty='psychiatry', td_causing_medications_addressed=addressed,
             suicidal=True, untreated_or_inadequately_treated_depression=True,
             generic_tetrabenazine_manufacturers_failed=0)
    assert evaluate(PACK, f).decision == 'pass'


def test_product_isolation():
    assert evaluate(PACK, dict(facts('ingrezza', HD), significant_hepatic_impairment=True)).decision == 'pass'
    assert evaluate(PACK, dict(facts('xenazine', HD), prescriber_specialty='psychiatry')).decision == 'fail'
    assert evaluate(PACK, dict(facts('xenazine', TD))).decision == 'fail'
    for product in PRODUCTS[:3]:
        assert evaluate(PACK, dict(facts(product, HD), baseline_aims=0,
                                  aims_lines_1_7_max_score=0,
                                  td_causing_medications_addressed='not_addressed',
                                  prescriber_specialty='psychiatry')).decision == 'pass'


@pytest.mark.parametrize('product,indication', PATHS)
def test_ui(product, indication):
    f = facts(product, indication)
    detail = drug_detail('vesicular-monoamine')
    assert detail['can_evaluate']
    fields = {v['key']: v for v in detail['fact_fields']}
    assert {k for k,v in fields.items() if _when_applies(v.get('when'), f)} == set(f)
    for key in f:
        field = fields[key]
        assert field['type'] == 'select' and not field.get('free_text')
        for opt in field['options']:
            result = evaluate(PACK, _coerce_patient(dict(f, **{key: opt['value']})))
            if key in ['product', 'indication']:
                continue  # Changing paths can require newly applicable facts.
            denied = (opt['value'] in ['17', 'other', 'not_addressed', '7', '2', '0', '1']
                      or (key.startswith('concurrent_') and opt['value'] == 'yes')
                      or (key in ['significant_hepatic_impairment', 'suicidal',
                                  'untreated_or_inadequately_treated_depression'] and opt['value'] == 'yes')
                      or (product == 'xenazine' and key == 'prescriber_specialty' and opt['value'] == 'psychiatry'))
            if key == 'generic_tetrabenazine_manufacturers_failed' and opt['value'] == '2':
                denied = False
            assert result.decision == ('fail' if denied else 'pass'), (key, opt)
    coerced = _coerce_patient({k: ('yes' if v else 'no') if isinstance(v, bool) else str(v) for k,v in f.items()})
    assert evaluate(PACK, coerced).decision == 'pass'


def test_metadata_catalog_and_notes():
    assert PACK['encoding_status'] == 'partial'
    assert PACK['drug']['therapeutic_class'] == 'vmat2-inhibitor'
    assert PACK['source']['effective_date'] == '2025-11-01'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for text in ['Austedo', 'Ingrezza', 'Xenazine', 'akathisia', 'parkinsonism', 'Sedation',
                 'QTc', '3 months', '12 months', '≥2-point', '≥3', '34-day', '24 mg 2 tablets/day', 'manual review']:
        assert text in notes
    assert evaluate(PACK, dict(facts('austedo', TD), authorization_type='renewal', requested_units=999)).decision == 'pass'
    assert evaluate(PACK, {}).decision == 'need_info'
    catalog = load_rule_pack_catalog()
    assert catalog['vesicular-monoamine'] == PACK
    assert (BASE/'vesicular-monoamine.json').read_bytes() == (BASE/'rule_packs/vesicular-monoamine.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 153
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 45
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (153, 45)
        assert status['next_candidate'] == 'movantik'
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status']=='partial')
    assert catalog['bone-resorption-inhibitors']['encoding_status'] == 'partial'
