"""Oxervate: source-specific gates, UI choices, missing facts and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/oxervate.json').read_text())
FACTS = dict(
    indication='neurotrophic_keratitis', age_years=2,
    nk_stage='stage_2_persistent_epithelial_defect',
    prescriber_specialty='ophthalmologist_or_optometrist_or_consult',
    decreased_corneal_sensitivity='decreased_in_at_least_one_eye',
    conventional_nonsurgical_nk_treatment='one_or_more_documented',
)


@pytest.mark.parametrize('fact,allowed,denied', [
    ('nk_stage', ['stage_2_persistent_epithelial_defect', 'stage_3_corneal_ulcer'], ['stage_1_or_not_documented']),
    ('prescriber_specialty', [FACTS['prescriber_specialty']], ['none']),
    ('decreased_corneal_sensitivity', ['decreased_in_at_least_one_eye'], ['not_documented']),
    ('conventional_nonsurgical_nk_treatment', ['one_or_more_documented'], ['none']),
])
def test_clinical_gates(fact, allowed, denied):
    assert {o['value'] for o in PACK['fact_ui'][fact]['options']} == set(allowed + denied)
    for value in allowed + denied:
        result = evaluate(PACK, dict(FACTS, **{fact: value}))
        assert result.decision == ('pass' if value in allowed else 'fail')
        assert {c['id'] for c in result.failed_clauses} == (set() if value in allowed else {fact})
        assert result.citations


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', 'other', True, False])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'indication'}


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (1.99, 'fail'), (2, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    result = evaluate(PACK, dict(FACTS, age_years=age))
    assert result.decision == decision
    assert {c['id'] for c in result.failed_clauses} == ({'minimum_age'} if decision == 'fail' else set())


def test_ui():
    fields = {f['key']: f for f in drug_detail('oxervate')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert fields['age_years']['option_style'] == 'age_bands'
    assert fields['indication']['options'] == [{'value': 'neurotrophic_keratitis', 'label': 'Neurotrophic keratitis (NK)'}]
    assert all('when' not in c for c in PACK['criteria'])
    assert all('when' not in f for f in PACK['fact_ui'].values())
    for field in fields.values():
        assert field['type'] == 'select' and not field.get('free_text')
    for option in fields['age_years']['options']:
        patient = _coerce_patient(dict(FACTS, age_years=option['value']))
        assert evaluate(PACK, patient).decision == ('pass' if patient['age_years'] >= 2 else 'fail')


def test_metadata_and_catalog():
    assert len(PACK['criteria']) == 6
    assert PACK['drug'] == dict(name='Oxervate', generic_name='cenegermin-bkbj', therapeutic_class='ophthalmology')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2020-11-16'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/l0cpkixo/202009oxervate_criteria_2020.pdf'
    assert PACK['source']['criteria_pdf'] == 'data/alaska/raw/202009oxervate_criteria_2020.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['Version 1', '07/06/2020', '09/18/2020', '11/16/2020', '8 weeks', 'Retreatment', 'lost or stolen', 'spilled', '8 kits per affected eye', '7 multi-dose vials', '15 minutes', 'eye pain', 'ocular hyperemia', 'inflammation', 'lacrimation', 'storage', 'manual review']:
        assert text in ' '.join(PACK['notes'])
    assert (BASE / 'oxervate.json').read_bytes() == (BASE / 'rule_packs/oxervate.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 151
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 47
    for slug in ['actiq', 'andembry']:
        assert catalog[slug]['encoding_status'] == 'partial'
    assert catalog['lemtrada']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert status['encoding_partial'] == 151 and status['encoding_text_only'] == 47
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'lovaza'
