"""Tzield source gates, closed indication, UI attestations, and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/tzield.json').read_text())
FACTS = dict(
    indication='stage_2_type_1_diabetes', age_years=8,
    islet_autoantibodies_confirmed=True, dysglycemia_confirmed=True,
    baseline_labs_obtained=True, body_surface_area_submitted=True,
    no_stage_3_type_1_diabetes=True, no_type_2_diabetes_history=True,
    no_active_serious_or_chronic_infection=True, baseline_lab_eligibility=True,
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


@pytest.mark.parametrize('value', ['stage_1_type_1_diabetes', 'stage_3_type_1_diabetes', 'type_2_diabetes', 'other', 'yes', 'no', True, False])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'indication'}


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (7.99, 'fail'), (8, 'pass'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


@pytest.mark.parametrize('fact', [f for f in FACTS if f not in {'age_years', 'indication'}])
def test_unmet_gate(fact):
    result = evaluate(PACK, dict(FACTS, **{fact: False}))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {fact}
    assert result.citations


def test_ui_options():
    fields = {f['key']: f for f in drug_detail('tzield')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == ['stage_2_type_1_diabetes']
    assert all('when' not in c for c in PACK['criteria'])
    for fact, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{fact: value})))
            assert result.decision == ('fail' if value in {'no', '0'} else 'pass'), (fact, value)


def test_source_thresholds_and_notes():
    labels = ' '.join(c['text'] for c in PACK['criteria'])
    for phrase in ['TWO or more', 'ICA', 'IA-2A', 'IAA', 'ZnT8A', 'GAD65', 'if oral GTT is unavailable', 'm²', 'EBV', 'CMV', '≥1,000/mcL', '≥10 g/dL', '≥150,000/mcL', 'ALT and AST ≤2×ULN', '≤1.5×ULN']:
        assert phrase in labels
    for phrase in ['Version 1', '12/27/2022', '01/20/2023', '03/01/2023', '3 months', 'Reauthorization not approved', '14 consecutive days', '65 mcg/m²', '125 mcg/m²', '250 mcg/m²', '500 mcg/m²', '1,030 mcg/m²', '30 minutes', '>5×ULN', '<500 cells/mcL', '1 week', '30 days', 'pregnancy', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])


def test_metadata_and_catalog():
    assert PACK['drug'] == dict(name='Tzield', generic_name='teplizumab-mzwv', therapeutic_class='cd3-monoclonal')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2023-03-01'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/fx4jn0rx/202301tzield_criteria_2023.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert len(PACK['criteria']) == 10
    assert 'inferred_required_facts' not in PACK
    assert (BASE / 'tzield.json').read_bytes() == (BASE / 'rule_packs/tzield.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 144
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 54
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (144, 54)
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'bone-resorption-inhibitors'
        assert catalog[status['next_candidate']]['encoding_status'] == 'text_only'
    assert (BASE / 'ENCODING_STATUS.md').read_bytes() == (BASE.parent / 'ENCODING_STATUS.md').read_bytes()
