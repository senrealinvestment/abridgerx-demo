"""Serostim Version 2: HIV wasting only, including independent OR paths."""
import gzip
import json
import sys
from itertools import product
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
IND = 'hiv_aids_wasting_cachexia'
STEP = ['dronabinol_failed_or_contraindicated', 'megestrol_failed_or_contraindicated']
WEIGHT = ['unintentional_loss_gt_10_percent_baseline', 'weight_lt_90_percent_lower_limit_ideal_body_weight', 'bmi_lt_20', 'lost_gt_5_percent_body_weight_past_6_months']
SYNDROME = ['chronic_diarrhea_ge_2_loose_stools_daily_ge_30_days', 'chronic_weakness_and_fever_intermittent_or_constant_ge_30_days']
BOOLS = ['hiv_positive', 'currently_receiving_antiretroviral_therapy', 'other_causes_of_weight_loss_ruled_out', 'not_for_athletic_recreational_social_body_mass', 'not_for_anti_aging', 'no_gh_contraindications_malignancy_retinopathy_critical_illness', 'not_concurrent_increlex']
GATED = BOOLS[:3] + ['failed_or_contraindication_dronabinol_or_megestrol', 'serostim_weight_loss_severity', 'serostim_clinical_syndrome']


def pack():
    return json.loads((BASE / 'rule_packs/serostim.json').read_text())


def facts():
    return dict.fromkeys(BOOLS, True) | {'indication': IND, 'failed_or_contraindication_dronabinol_or_megestrol': STEP[0], 'serostim_weight_loss_severity': WEIGHT[0], 'serostim_clinical_syndrome': SYNDROME[0]}


def test_metadata_and_scope():
    p = pack()
    assert p['drug'] == {'name': 'Serostim', 'generic_name': 'somatropin', 'therapeutic_class': 'growth-hormones'}
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2016-10-03'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/ippd24os/ccfu_growthhormones_serostim_20161003.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/ccfu_growthhormones_serostim_20161003.pdf'
    assert 'inferred_required_facts' not in p
    assert p['alternatives'] == []
    assert set(p['fact_ui']) == set(facts())
    assert {c['id'] for c in p['criteria']} == (set(facts()) - {'indication'}) | {'indication_fda_labeled'}
    notes = ' '.join(p['notes'])
    for text in ['Version 2', '4/15/2016', '4/29/2016', '6 months', '12 months', 'Quantity limit: None', 'lean body mass and body weight', 'physical endurance', 'weight loss was unaffected', 'IGF-1']:
        assert text in notes


@pytest.mark.parametrize('step,weight,syndrome', list(product(STEP, WEIGHT, SYNDROME)))
def test_every_independent_approval_path(step, weight, syndrome):
    f = facts() | {'failed_or_contraindication_dronabinol_or_megestrol': step, 'serostim_weight_loss_severity': weight, 'serostim_clinical_syndrome': syndrome}
    assert evaluate(pack(), f).decision == 'pass'


@pytest.mark.parametrize('fact,value', [(f, False) for f in BOOLS] + [('failed_or_contraindication_dronabinol_or_megestrol', 'neither'), ('serostim_weight_loss_severity', 'not_met'), ('serostim_clinical_syndrome', 'not_met')] + [('indication', v) for v in ['yes', 'no', 'unknown', True, False, 'growth_hormone_deficiency', 'hiv_lipodystrophy_excess_abdominal_fat']])
def test_each_denial(fact, value):
    result = evaluate(pack(), facts() | {fact: value})
    assert result.decision == 'fail'
    assert ('indication_fda_labeled' if fact == 'indication' else fact) in {c['id'] for c in result.failed_clauses}


@pytest.mark.parametrize('fact', list(facts()))
def test_missing_fact(fact):
    f = facts()
    del f[fact]
    result = evaluate(pack(), f)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


def test_gating_and_ui():
    p = pack()
    fields = {f['key']: f for f in drug_detail('serostim')['fact_fields']}
    assert set(fields) == set(facts())
    for f, field in fields.items():
        assert field['type'] == 'select'
        assert field['option_source'] == 'fact_ui'
        assert field['options'] == p['fact_ui'][f]['options']
    for f in GATED:
        c = next(c for c in p['criteria'] if c['id'] == f)
        assert c['when'] == fields[f]['when'] == {'fact': 'indication', 'in': [IND]}
    for indication in [None, 'growth_hormone_deficiency']:
        result = evaluate(p, {f: True for f in BOOLS[3:]} | {'indication': indication})
        assert result.decision == ('need_info' if indication is None else 'fail')
        assert not set(GATED).intersection(result.missing_facts)
    assert fields['indication']['options'] == [{'value': IND, 'label': 'HIV/AIDS-associated wasting syndrome/cachexia'}]
    for f in BOOLS:
        for answer, expected in [('yes', 'pass'), ('no', 'fail')]:
            assert evaluate(p, _coerce_patient(facts() | {f: answer})).decision == expected
    for f, values in [('failed_or_contraindication_dronabinol_or_megestrol', STEP), ('serostim_weight_loss_severity', WEIGHT), ('serostim_clinical_syndrome', SYNDROME)]:
        assert next(c for c in p['criteria'] if c['id'] == f)['predicate'] == {'op': 'in', 'fact': f, 'values': values}
        assert evaluate(p, facts() | {f: 'unsupported'}).decision == 'fail'


def test_catalog_and_mirrors():
    p = pack()
    catalog = load_rule_pack_catalog()
    assert catalog['serostim'] == p == json.loads((BASE / 'serostim.json').read_text())
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 74
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 124
    assert catalog['somatropin']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 74 and status['encoding_text_only'] == 124
    assert status['next_candidate'] == 'spinal-muscular-atrophy'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    assert (BASE / 'ENCODING_STATUS.json').read_bytes() == (BASE.parent / 'ENCODING_STATUS.json').read_bytes()
    assert (BASE / 'ENCODING_STATUS.md').read_bytes() == (BASE.parent / 'ENCODING_STATUS.md').read_bytes()
