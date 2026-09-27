"""Alaska S1P product/indication boundaries and independent approval/denial gates."""
import gzip
import itertools
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
SLUG = 'sphingosine-1-phosphate-receptor'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
MS = ['clinically_isolated_syndrome', 'relapsing_remitting_ms', 'active_secondary_progressive_ms']
UC = 'moderately_to_severely_active_ulcerative_colitis'


def facts(product='siponimod', indication=MS[0]):
    f = dict(product=product, indication=indication, age_years=18,
             baseline_ecg_cbc_lft_ophthalmic_6mo='all_done_within_6mo_appropriate',
             no_recent_major_cv_event_6mo='no_mi_ua_stroke_tia_decomp_hf_or_class_iii_iv_hf_in_6mo',
             av_block_sss_status='no_mobitz_ii_third_degree_or_sss',
             not_concurrent_ms_dmt=True, not_pregnant=True)
    if indication == UC:
        f.update(uc_prescriber_specialty='gastroenterologist_or_consult',
                 uc_systemic_step='two_systemic_including_one_biologic_failed')
    else:
        f.update(prescriber_specialty='neurologist_or_ms_specialist_or_consult',
                 ms_dmt_step_two='trial_failure_two_ms_drugs')
    if product == 'ozanimod':
        f['no_severe_sleep_apnea'] = True
    return f


@pytest.mark.parametrize('product,indication', list(itertools.product(
    ['siponimod', 'ponesimod', 'ozanimod', 'etrasimod'], MS + [UC])))
def test_product_indication_matrix(product, indication):
    allowed = product in (['ozanimod', 'etrasimod'] if indication == UC else ['siponimod', 'ponesimod', 'ozanimod'])
    r = evaluate(PACK, facts(product, indication))
    assert r.decision == ('pass' if allowed else 'fail')
    if not allowed:
        assert [c['id'] for c in r.failed_clauses] == [product + '_indication']


PATHS = [('siponimod', MS[0]), ('ponesimod', MS[1]), ('ozanimod', MS[2]), ('ozanimod', UC), ('etrasimod', UC)]


@pytest.mark.parametrize('product,indication', PATHS)
def test_missing_and_null_active_facts(product, indication):
    f = facts(product, indication)
    for key in f:
        for null in [False, True]:
            changed = f.copy()
            if null:
                changed[key] = None
            else:
                del changed[key]
            r = evaluate(PACK, changed)
            assert r.decision == 'need_info'
            assert r.missing_facts == [key]
    assert evaluate(PACK, {}).decision == 'need_info'


@pytest.mark.parametrize('product,indication', PATHS)
def test_each_gate_independently_fails(product, indication):
    f = facts(product, indication)
    for key, value in f.items():
        bad = 17.99 if key == 'age_years' else False if isinstance(value, bool) else 'not_met'
        r = evaluate(PACK, dict(f, **{key: bad}))
        assert r.decision == 'fail', (key, r)
        assert r.failed_clauses and r.citations
    assert evaluate(PACK, dict(f, age_years=90)).decision == 'pass'
    assert evaluate(PACK, dict(f, av_block_sss_status='has_condition_with_functioning_pacemaker')).decision == 'pass'
    for bad in ['has_condition_without_pacemaker_or_not_attested', 'unknown']:
        assert evaluate(PACK, dict(f, av_block_sss_status=bad)).decision == 'fail'


def test_stale_other_path_facts_and_product_only_denial():
    for product, indication in PATHS:
        f = facts(product, indication)
        stale = dict(prescriber_specialty='none', ms_dmt_step_two='none') if indication == UC else dict(uc_prescriber_specialty='none', uc_systemic_step='not_met')
        assert evaluate(PACK, dict(f, **stale)).decision == 'pass'
        assert evaluate(PACK, dict(f, no_severe_sleep_apnea=False)).decision == ('fail' if product == 'ozanimod' else 'pass')
        # Cautions and separate Mayzent source requirements are not new denials.
        assert evaluate(PACK, dict(f, cyp2c9_genotype='star3_star3_or_not_tested', baseline_skin_exam_done='not_conducted', requested_units=999)).decision == 'pass'
    for bad in ['ulcerative_colitis', 'mild_ulcerative_colitis', 'primary_progressive_ms', 'other', True]:
        assert evaluate(PACK, dict(facts(), indication=bad)).decision == 'fail'


def test_ui_options_and_gates():
    fields = {f['key']: f for f in drug_detail(SLUG)['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    for product, indication in PATHS:
        f = facts(product, indication)
        assert evaluate(PACK, _coerce_patient({k: ('yes' if v is True else str(v)) for k, v in f.items()})).decision == 'pass'
        for key, field in fields.items():
            assert field['type'] == 'select' and not field.get('free_text')
            if _when_applies(field.get('when'), f):
                for option in field['options']:
                    result = evaluate(PACK, _coerce_patient(dict(f, **{key: option['value']})))
                    if key not in ['product', 'indication']:
                        assert result.decision in ['pass', 'fail']
                    else:
                        assert result.decision in ['pass', 'fail', 'need_info']
    assert fields['uc_systemic_step']['when'] == {'fact': 'indication', 'eq': UC}
    assert fields['no_severe_sleep_apnea']['when'] == {'fact': 'product', 'eq': 'ozanimod'}
    assert PACK['drug']['therapeutic_class'] == 's1p-receptor-modulator'
    assert PACK['source']['effective_date'] == '2024-03-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and 'inferred_required_facts' not in PACK
    for phrase in ['6 months', '12 months', '34-day', 'PRES', 'uveitis', 'skin malignancies', 'CYP2C9', 'CYP3A4', '4 weeks', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])


def test_catalog_mirrors_status_and_reciprocal_peer():
    catalog = load_rule_pack_catalog()
    assert catalog[SLUG] == PACK
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 165
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 33
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    assert SLUG in catalog['vumerity']['alternatives']
    for d in [BASE, BASE.parent]:
        s = json.loads((d / 'ENCODING_STATUS.json').read_text())
        assert (s['encoding_partial'], s['encoding_text_only']) == (165, 33)
        assert s['next_candidate'] == 'transderm-scop'
        assert s['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
