"""Lucemyra's closed indication, approval mirrors, and clonidine/ED alternatives."""
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
PACK = json.loads((BASE / 'rule_packs/lucemyra.json').read_text())
CORE = dict(indication='opioid_withdrawal_mitigation', age_years=18,
            confirmed_opioid_dependence_or_oud=True, pain_or_addiction_specialist=True,
            abrupt_opioid_discontinuation=True, normal_qt_interval=True)
PATHS = ['clonidine_failed_within_6_months', 'clonidine_contraindicated',
         'clonidine_significant_adverse_effect', 'lucemyra_initiated_in_ed']
FACTS = {**CORE, **dict.fromkeys(PATHS, False), 'lucemyra_initiated_in_ed': True}


@pytest.mark.parametrize('values', list(itertools.product([None, False, True], repeat=4)))
def test_four_way_choice(values):
    result = evaluate(PACK, dict(CORE, **dict(zip(PATHS, values))))
    expected = 'pass' if True in values else 'need_info' if None in values else 'fail'
    assert result.decision == expected
    assert result.missing_facts == ([k for k,v in zip(PATHS, values) if v is None]
                                    if expected == 'need_info' else [])
    assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('key', CORE)
@pytest.mark.parametrize('omit', [False, True])
def test_missing_core(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('key,value', [
    ('indication', 'other'), ('indication', True), ('age_years', 17),
    ('age_years', 17.99), ('confirmed_opioid_dependence_or_oud', False),
    ('pain_or_addiction_specialist', False), ('abrupt_opioid_discontinuation', False),
    ('normal_qt_interval', False)])
def test_denial_mirrors(key, value):
    result = evaluate(PACK, dict(FACTS, **{key: value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]


@pytest.mark.parametrize('path', PATHS)
def test_each_path_alone(path):
    assert evaluate(PACK, dict(CORE, **{path: True})).decision == 'pass'


def test_ui_and_notes():
    detail = drug_detail('lucemyra')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(CORE) | set(PATHS)
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            facts = {**FACTS, **dict.fromkeys(PATHS, False), key: option['value']}
            if key not in PATHS:
                facts['lucemyra_initiated_in_ed'] = True
            result = evaluate(PACK, _coerce_patient(facts))
            deny = option['value'] in ['no', '17']
            assert result.decision == ('fail' if deny else 'pass')
    notes = ' '.join(PACK['notes'])
    for phrase in ['hypotension', 'bradycardia', 'syncope', 'prolonged QT', 'CNS depressants',
                   'hepatic', 'renal', '2–4 days', '7 days (112 tablets)', 'positive patient response',
                   '3–7 days', '14 days per month', 'three 14-day treatments per year', 'manual review']:
        assert phrase in notes
    assert PACK['drug']['generic_name'] == 'lofexidine'
    assert PACK['drug']['therapeutic_class'] == 'central-alpha2-agonist'
    assert PACK['source']['effective_date'] == '2019-03-11'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert evaluate(PACK, dict(FACTS, requested_units=9999, authorization_type='renewal')).decision == 'pass'
    assert evaluate(PACK, {}).decision == 'need_info'


def test_catalog():
    catalog = load_rule_pack_catalog()
    assert catalog['lucemyra'] == PACK
    assert (BASE/'lucemyra.json').read_bytes() == (BASE/'rule_packs/lucemyra.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 180
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 18
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (180, 18)
        assert status['next_candidate'] == 'brand-name-multisource-medications'
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status']=='partial')
    assert catalog['bone-resorption-inhibitors']['encoding_status'] == 'partial'
