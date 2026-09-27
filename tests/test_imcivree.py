"""Alaska Imcivree branch gates, source thresholds and catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/imcivree.json').read_text())
D = 'pomc_pcsk1_lepr_deficiency_obesity'
B = 'bardet_biedl_syndrome_obesity'
SHARED = dict(age_years=2, prescriber_specialty='endocrinologist',
              baseline_weight_bmi_documented=True,
              not_suicidal_no_uncontrolled_depression=True,
              no_benign_deficiency_variants=True, no_unrelated_obesity=True,
              no_moderate_severe_esrd=True, not_pregnant_or_breastfeeding=True)
BRANCH = {
    D: dict(qualifying_genetic_testing=True, qualifying_variant='vus',
            deficiency_weight_eligibility='age_2_6_weight_gte_15kg_97th',
            sexual_adverse_reaction_counseling=True),
    B: dict(bbs_weight_eligibility='age_2_17_weight_gte_15kg_97th',
            other_obesity_causes_ruled_out=True),
}


def facts(indication):
    return dict(SHARED, indication=indication, **BRANCH[indication])


@pytest.mark.parametrize('indication', [D, B])
def test_branch_pass_missing_denials_and_hidden_answers(indication):
    patient = facts(indication)
    assert evaluate(PACK, patient).decision == 'pass'
    for key in patient:
        missing = patient.copy()
        del missing[key]
        result = evaluate(PACK, missing)
        assert result.decision == 'need_info' and result.missing_facts == [key]
        if key not in {'age_years', 'indication'}:
            result = evaluate(PACK, dict(patient, **{key: False}))
            assert result.decision == 'fail'
            assert [c['id'] for c in result.failed_clauses] == [key]
    other = B if indication == D else D
    assert evaluate(PACK, dict(patient, **dict.fromkeys(BRANCH[other], False))).decision == 'pass'
    fields = {f['key']: f for f in drug_detail('imcivree')['fact_fields']}
    assert {k for k, f in fields.items() if _when_applies(f.get('when'), patient)} == set(patient)
    for c in PACK['criteria']:
        assert fields[c['id']].get('when') == c.get('when')
    for key in patient:
        field = fields[key]
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            selected = facts(value) if key == 'indication' else dict(patient, **{key: value})
            result = evaluate(PACK, _coerce_patient(selected))
            assert result.decision == ('fail' if value in {'no', 'none', '0'} else 'pass')


@pytest.mark.parametrize('indication', [D, B])
@pytest.mark.parametrize('age,decision', [(0, 'fail'), (1.99, 'fail'), (2, 'pass'), (6, 'pass'), (17, 'pass'), (18, 'pass')])
def test_age_floor(indication, age, decision):
    assert evaluate(PACK, dict(facts(indication), age_years=age)).decision == decision


@pytest.mark.parametrize('value', ['other', 'polygenic_obesity', 'yes', 'no', True, False])
def test_closed_indication(value):
    result = evaluate(PACK, dict(facts(D), indication=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


@pytest.mark.parametrize('indication,key,wrong', [
    (D, 'qualifying_variant', 'benign'), (D, 'qualifying_variant', 'likely_benign'),
    (D, 'deficiency_weight_eligibility', 'age_2_17_weight_gte_15kg_97th'),
    (B, 'bbs_weight_eligibility', 'age_6_17_weight_gte_95th'),
    (B, 'prescriber_specialty', 'cardiologist'),
])
def test_unqualified_selections(indication, key, wrong):
    result = evaluate(PACK, dict(facts(indication), **{key: wrong}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]


def test_metadata_source_thresholds_and_notes():
    assert PACK['drug'] == dict(name='Imcivree', generic_name='setmelanotide', therapeutic_class='mc4-receptor-agonist')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2026-03-01'
    assert PACK['alternatives'] == [] and PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert [o['value'] for o in PACK['fact_ui']['indication']['options']] == [D, B]
    labels = ' '.join(o['label'] for k in ['deficiency_weight_eligibility', 'bbs_weight_eligibility'] for o in PACK['fact_ui'][k]['options'])
    for phrase in ['Age ≥18: BMI ≥30', 'Age 6–17: weight ≥95th', 'Age 2–6: weight ≥15 kg AND ≥97th', 'Age 2–17: weight ≥15 kg AND ≥97th']:
        assert phrase in labels
    notes = ' '.join(PACK['notes'])
    for phrase in ['Version 2', '2/27/2021', '12/23/2025', '03/01/2026', '3 months', '12 months', '≥5%', 'current weight or BMI', '9 ml per month', 'sexual arousal', 'suicidal ideation', 'pigmentation', 'Benzyl alcohol', 'gasping syndrome', 'manual review']:
        assert phrase in notes


def test_catalog_and_mirror():
    assert (BASE / 'imcivree.json').read_bytes() == (BASE / 'rule_packs/imcivree.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 119
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 79
    assert catalog['epidiolex']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (119, 79)
        assert status['next_candidate'] == 'vumerity'
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
