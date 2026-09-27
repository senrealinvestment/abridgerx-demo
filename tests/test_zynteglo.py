"""Zynteglo Alaska Medicaid Version 1 eligibility and catalog regressions."""
import gzip
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
PATHS = ['prbc_ge_100_ml_per_kg_per_year_prior_2_years',
         'prbc_transfusions_ge_8_prior_2_years']
GATED = {
    'beta_thalassemia_genetic_testing_confirmed',
    'adequate_cd34_cells_for_min_dose_5e6_per_kg',
    'negative_hbv_hcv_hiv_htlv_prior_to_cell_collection',
    'tdt_transfusion_history', 'no_prior_gene_therapy_for_tdt',
    'no_prior_allogeneic_hsct_for_tdt',
}


def pack():
    return json.loads((BASE / 'rule_packs/zynteglo.json').read_text())


def facts(**updates):
    return dict(dict(
        indication='beta_thalassemia_transfusion_dependent', age_years=4,
        prescriber_specialty='hematologist', weight_kg=6,
        beta_thalassemia_genetic_testing_confirmed=True,
        adequate_cd34_cells_for_min_dose_5e6_per_kg=True,
        negative_hbv_hcv_hiv_htlv_prior_to_cell_collection=True,
        tdt_transfusion_history=PATHS[0],
        no_prior_gene_therapy_for_tdt=True,
        no_prior_allogeneic_hsct_for_tdt=True), **updates)


def assert_failure(clause, **updates):
    result = evaluate(pack(), facts(**updates))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {clause}
    assert result.citations == [pack()['source']['citation']]


def test_closed_indication_age_and_specialty():
    for specialty in ['hematologist', 'hematologist_consult']:
        for age in [4, 4.01, 18, 80]:
            assert evaluate(pack(), facts(age_years=age, prescriber_specialty=specialty)).decision == 'pass'
    for value in ['yes', 'no', 'unknown', True, False, 'hemophilia_b_moderate_severe', 'hemophilia_a', 'other']:
        assert_failure('indication_fda_labeled', indication=value)
    for age in [0, 3, 3.99]:
        assert_failure('age_fda_labeled', age_years=age)
    assert_failure('prescriber_specialty', prescriber_specialty='other')


def test_weight_and_both_transfusion_paths():
    for weight in [6, 6.01, 80]:
        for path in PATHS:
            assert evaluate(pack(), facts(weight_kg=weight, tdt_transfusion_history=path)).decision == 'pass'
    for weight in [0, 5, 5.99]:
        assert_failure('weight_minimum', weight_kg=weight)
    for value in ['not_met', 'yes', 'no', 'unknown', True, False, 'prbc_transfusions_ge_8_per_year']:
        assert_failure('tdt_transfusion_history', tdt_transfusion_history=value)


@pytest.mark.parametrize('fact', [f for f, value in facts().items() if value is True])
def test_approval_attestations_and_explicit_denials(fact):
    # Denial 1 is failure of any approval clause; denials 2-3 are explicit exclusions.
    assert_failure(fact, **{fact: False})


@pytest.mark.parametrize('fact', facts())
@pytest.mark.parametrize('missing', [None, 'absent'])
def test_missing_needs_information(fact, missing):
    patient = facts()
    if missing == 'absent':
        del patient[fact]
    else:
        patient[fact] = None
    result = evaluate(pack(), patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


def test_when_gating_and_ui_options():
    fields = {f['key']: f for f in drug_detail('zynteglo')['fact_fields']}
    assert set(fields) == set(facts())
    gate = {'fact': 'indication', 'in': ['beta_thalassemia_transfusion_dependent']}
    assert {c['required_facts'][0] for c in pack()['criteria'] if c.get('when') == gate} == GATED
    for f in GATED:
        assert fields[f]['when'] == gate
    for indication in ['other', None]:
        patient = {k: v for k, v in facts(indication=indication).items() if k not in GATED}
        result = evaluate(pack(), patient)
        assert result.decision == ('fail' if indication else 'need_info')
        assert not GATED.intersection(result.missing_facts)
    assert [o['value'] for o in fields['indication']['options']] == ['beta_thalassemia_transfusion_dependent']
    raw = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
    for fact, field in fields.items():
        assert field['type'] == 'select'
        for option in field['options']:
            value = option['value']
            good = value == raw[fact] or (fact == 'prescriber_specialty' and value == 'hematologist_consult') or (fact == 'tdt_transfusion_history' and value in PATHS)
            result = evaluate(pack(), _coerce_patient(dict(raw, **{fact: value})))
            assert result.decision == ('pass' if good else 'fail'), (fact, value)


def test_metadata_notes_catalog_and_mirrors():
    p = pack()
    assert p['drug'] == dict(name='Zynteglo', generic_name='betibeglogene autotemcel', therapeutic_class='cell-and-gene-therapy')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2025-01-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/rkkfapch/zynteglo_criteria_2024.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/zynteglo_criteria_2024.pdf'
    assert p['alternatives'] == [] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 10
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '10/9/2024', '11/15/2024', '01/01/2025', '6 months',
                 'no reauthorization', 'one infusion per lifetime', 'J3393', 'platelet',
                 'neutrophil', '15 years', 'hydroxyurea', 'antiretroviral',
                 'seven days', 'six months', 'DMSO', 'manual review']:
        assert text in ' '.join(p['notes'])
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 152
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 46
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'zynteglo.json').read_bytes() == (BASE / 'rule_packs/zynteglo.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (152, 46)
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'marinol'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


@pytest.mark.parametrize('value', ['5.99', '6', '6.01'])
def test_numeric_weight_form_input(value):
    patient = _coerce_patient(dict(facts(), weight_kg=value))
    assert patient['weight_kg'] == float(value)
    assert evaluate(pack(), patient).decision == ('pass' if float(value) >= 6 else 'fail')


@pytest.mark.parametrize('value', ['', None, 'invalid'])
def test_invalid_weight_form_input_needs_information(value):
    result = evaluate(pack(), _coerce_patient(dict(facts(), weight_kg=value)))
    assert result.decision == 'need_info'
    assert result.missing_facts == ['weight_kg']
