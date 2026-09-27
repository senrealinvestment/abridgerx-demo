"""Uptravi source gates, therapy attestation, interaction exception and catalog."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, find_alternatives
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/uptravi.json').read_text())
FACTS = dict(indication='pulmonary_arterial_hypertension_who_group_1', age_years=18,
             prescriber_specialty='cardiologist_or_pulmonologist_or_consult',
             pah_confirmed_by_right_heart_catheterization='rhc_confirmed',
             oral_pah_therapy_two_categories_ge_60d='two_or_more_categories_each_ge_60d',
             prostanoid_prostacyclin_analogue_exclusion='no_current_or_planned_use',
             strong_cyp2c8_inhibitor='no_concomitant_use')


@pytest.mark.parametrize('key', [k for k in FACTS if k != 'age_years'])
def test_closed_gates(key):
    criterion = next(c for c in PACK['criteria'] if c['id'] == key)
    pred = criterion['predicate']
    allowed = pred.get('values', [pred.get('value')])
    options = [o['value'] for o in PACK['fact_ui'][key]['options']]
    for value in options + ['unknown', 'yes', 'no', True, False, 'other_pah']:
        result = evaluate(PACK, dict(FACTS, **{key: value}))
        assert result.decision == ('pass' if value in allowed else 'fail')
        assert {c['id'] for c in result.failed_clauses} == (set() if value in allowed else {key})
        assert result.citations


@pytest.mark.parametrize('age,decision', [(17, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [False, True])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('interaction', ['no_concomitant_use', 'benefits_outweigh_risks_attested'])
@pytest.mark.parametrize('use', ['current_use', 'planned_use'])
def test_interaction_exception_does_not_bypass_combination_exclusion(interaction, use):
    result = evaluate(PACK, dict(FACTS, strong_cyp2c8_inhibitor=interaction,
                               prostanoid_prostacyclin_analogue_exclusion=use))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['prostanoid_prostacyclin_analogue_exclusion']


def test_ui_source_and_notes():
    detail = drug_detail('uptravi')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert len(fields['indication']['options']) == 1
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert evaluate(PACK, _coerce_patient(dict(FACTS, age_years='18'))).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'selexipag'
    assert PACK['source']['effective_date'] == '2023-03-01'
    assert PACK['encoding_status'] == 'partial' and len(PACK['criteria']) == 7
    assert PACK['max_units'] is None and 'inferred_required_facts' not in PACK
    for text in ['PVOD', 'pulmonary edema', '6 months', '12 months', 'positive clinical response',
                 '#60 tablets', '#60 vials', '3200 mcg/day oral', '3600 mcg/day IV', 'J3490',
                 'only if not pregnant', 'each for at least 60 days', 'manual review']:
        assert text in ' '.join(PACK['notes'])


def test_catalog_mirror_and_alternatives():
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert catalog['uptravi'] == PACK
    assert PACK['alternatives'] == ['opsumit']
    assert 'uptravi' in catalog['opsumit']['alternatives']
    assert find_alternatives(PACK, FACTS, catalog)[0]['verification'] == 'evaluate_need_info'
    assert (BASE / 'uptravi.json').read_bytes() == (BASE / 'rule_packs/uptravi.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 152
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 46
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (152, 46)
        assert status['next_candidate'] == 'marinol'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
