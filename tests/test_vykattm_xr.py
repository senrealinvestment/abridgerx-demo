"""Vykat XR source criteria, closed choices, notes and catalog mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/vykattm-xr.json').read_text())
FACTS = dict(indication='hyperphagia_prader_willi_syndrome', age_years=4,
             prescriber_specialty='endocrinologist',
             pws_genetic_testing_chromosome_15_mutation=True,
             hyperphagia_present=True, hypersensitivity_diazoxide_or_thiazides=False)


@pytest.mark.parametrize('specialty', ['endocrinologist', 'endocrinologist_consult', 'geneticist', 'geneticist_consult'])
def test_specialists(specialty):
    result = evaluate(PACK, dict(FACTS, prescriber_specialty=specialty))
    assert result.decision == 'pass'
    assert result.citations


@pytest.mark.parametrize('key,value', [
    ('indication', 'prader_willi_syndrome'), ('indication', 'hyperphagia'),
    ('indication', 'other'), ('indication', True),
    ('age_years', 3.99), ('age_years', 0),
    ('prescriber_specialty', 'pediatrician'), ('prescriber_specialty', 'other'),
    ('pws_genetic_testing_chromosome_15_mutation', False),
    ('hyperphagia_present', False), ('hypersensitivity_diazoxide_or_thiazides', True),
])
def test_denials(key, value):
    result = evaluate(PACK, dict(FACTS, **{key: value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]


@pytest.mark.parametrize('age', [4, 4.01, 18, 80])
def test_age(age):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == 'pass'


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


def test_combined_and_empty():
    assert set(evaluate(PACK, {}).missing_facts) == set(FACTS)
    result = evaluate(PACK, dict(FACTS, hyperphagia_present=False, hypersensitivity_diazoxide_or_thiazides=True))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'hyperphagia_present', 'hypersensitivity_diazoxide_or_thiazides'}


def test_ui():
    detail = drug_detail('vykattm-xr')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == [FACTS['indication']]
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            denied = (value == 'yes' if key == 'hypersensitivity_diazoxide_or_thiazides' else value in {'no', '0', 'other'})
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{key: value})))
            assert result.decision == ('fail' if denied else 'pass'), (key, value)


def test_notes_and_metadata():
    assert PACK['drug']['generic_name'] == 'diazoxide choline'
    assert PACK['drug']['therapeutic_class'] == 'atp-sensitive-potassium-channel-activator'
    assert PACK['source']['effective_date'] == '2026-01-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert len(PACK['criteria']) == 6
    assert 'inferred_required_facts' not in PACK
    for phrase in ['HbA1c', 'fasting glucose', 'CYP1A2', 'edema', 'fluid overload', '3 months', 'one year', '120 tablets/30 days', '210 tablets/30 days', '90 tablets/30 days', 'weight-based target dose', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])
    assert evaluate(PACK, dict(FACTS, requested_units=9999, edema=True, strong_cyp1a2_inhibitor=True)).decision == 'pass'


def test_catalog():
    catalog = load_rule_pack_catalog()
    assert catalog['vykattm-xr'] == PACK
    assert (BASE / 'vykattm-xr.json').read_bytes() == (BASE / 'rule_packs/vykattm-xr.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 163
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 35
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (163, 35)
        assert status['next_candidate'] == 'vecamyl'
        assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    assert catalog['interleukin-5-inhibitors']['criteria']
