"""Oxbryta source gates, closed indication, UI attestations, and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/oxbryta.json').read_text())
FACTS = dict(
    indication='sickle_cell_disease', age_years=4,
    prescriber_specialty='hematologist_or_sickle_cell_specialist_or_consult',
    vaso_occlusive_crisis_within_6_months=True,
    baseline_hemoglobin_documented=True, hydroxyurea_requirement_met=True,
    no_concomitant_prophylactic_blood_transfusions=True,
    no_concomitant_adakveo=True,
)


def test_eligible():
    assert evaluate(PACK, FACTS).decision == 'pass'


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['myasthenia_gravis', 'other', 'yes', 'no', True, False])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'indication'}


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (3.99, 'fail'), (4, 'pass'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


@pytest.mark.parametrize('fact', [f for f in FACTS if f not in {'age_years', 'indication'}])
def test_unmet_gate(fact):
    result = evaluate(PACK, dict(FACTS, **{fact: False}))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {fact}
    assert result.citations


def test_ui_options():
    fields = {f['key']: f for f in drug_detail('oxbryta')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == ['sickle_cell_disease']
    assert all('when' not in c for c in PACK['criteria'])
    for fact, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{fact: value})))
            assert result.decision == ('fail' if value in {'no', '0', 'none'} else 'pass'), (fact, value)


@pytest.mark.parametrize('value', ['none', 'cardiologist', 'yes', True])
def test_unqualified_specialty(value):
    result = evaluate(PACK, dict(FACTS, prescriber_specialty=value))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'prescriber_specialty'}


def test_source_thresholds_and_notes():
    labels = ' '.join(c['text'] for c in PACK['criteria'])
    for phrase in ['in consultation', 'hematologist', 'sickle-cell specialist',
                   'at least one vaso-occlusive crisis', 'past 6 months',
                   'baseline hemoglobin', 'tried and failed OR', 'contraindication',
                   'hydroxyurea for at least 3 months', 'prophylactic blood transfusions', 'Adakveo']:
        assert phrase in labels
    for phrase in ['Version 2', '02/28/2020', '9/16/2022', '11/1/2022',
                   'accelerated pathway', 'CYP3A4', 'hypersensitivity',
                   '3 months', '12 months', 'increase in hemoglobin and/or decrease',
                   '90 × 500 mg', '90 × 300 mg', 'per 30 days', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])


def test_metadata_and_catalog():
    assert PACK['drug'] == dict(name='Oxbryta', generic_name='voxelotor', therapeutic_class='hemoglobin-s-polymerization-inhibitor')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2022-11-01'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/ygtdvp5d/202209-oxbryta_criteria_2022.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert len(PACK['criteria']) == 8
    assert 'inferred_required_facts' not in PACK
    assert (BASE / 'oxbryta.json').read_bytes() == (BASE / 'rule_packs/oxbryta.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 128
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 70
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (128, 70)
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'revatio'
        assert catalog[status['next_candidate']]['encoding_status'] == 'text_only'
    assert (BASE / 'ENCODING_STATUS.md').read_bytes() == (BASE.parent / 'ENCODING_STATUS.md').read_bytes()
