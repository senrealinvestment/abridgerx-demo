"""Metformin ER initial criteria, no grandfathering, UI gating and mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/metformin-er.json').read_text())
INDICATION = 'type_2_diabetes_mellitus'
GATES = ['tried_glucophage_xr_generic', 'inert_ingredient_allergy_glucophage_xr_not_in_requested', 'fda_medwatch_submitted']
FACTS = dict(indication=INDICATION, age_years=18, **dict.fromkeys(GATES, True))


def test_approval():
    result = evaluate(PACK, FACTS)
    assert result.decision == 'pass'
    assert result.citations


@pytest.mark.parametrize('key', GATES)
def test_each_condition_required_even_for_current_users(key):
    result = evaluate(PACK, dict(FACTS, **{key: False, 'current_therapy': True, 'positive_clinical_response': True}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]
    assert result.failed_clauses[0]['citation'] == PACK['source']['citation']


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [False, True])
def test_missing_or_unknown(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('indication', ['type_1_diabetes_mellitus', 'prediabetes', 'polycystic_ovary_syndrome', 'other', '', True, False])
def test_closed_indication(indication):
    result = evaluate(PACK, {'indication': indication})
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


def test_age_and_indication_gating():
    assert evaluate(PACK, dict(FACTS, age_years=17)).decision == 'fail'
    assert evaluate(PACK, {}).missing_facts == ['indication']
    assert evaluate(PACK, {'indication': INDICATION}).missing_facts == ['age_years'] + GATES


def test_ui_and_notes():
    detail = drug_detail('metformin-er')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(FACTS)
    assert PACK['fact_ui']['indication']['options'][0]['value'] == INDICATION
    for key in ['age_years'] + GATES:
        assert PACK['fact_ui'][key]['when'] == {'fact': 'indication', 'in': [INDICATION]}
    ui = dict(FACTS, **dict.fromkeys(GATES, 'yes'))
    assert evaluate(PACK, _coerce_patient(ui)).decision == 'pass'
    for key in GATES:
        assert evaluate(PACK, _coerce_patient(dict(ui, **{key: 'no'}))).decision == 'fail'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['requires_pa'] is True
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert len(PACK['criteria']) == 5
    notes = ' '.join(PACK['notes'])
    for phrase in ['not permitted', 'positive clinical response', 'better tolerance', '6 months', '1 year', 'Fortamet 2 tablets/day', 'Glumetza 2 tablets/day', '500 mg/750 mg', '500 mg/1000 mg', 'Version 1', '4/7/2016', '4/29/2016', '10/3/2016', 'Pharmacokinetics', 'Mechanism', 'references']:
        assert phrase in notes
    source = json.loads((BASE / 'criteria_text/metformin-er.json').read_text())
    assert PACK['source']['effective_date'] == source['effective_date'] == '2016-10-03'
    assert PACK['source']['citation'] == source['source_url']


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['metformin-er'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'metformin-er.json').read_bytes() == (BASE / 'rule_packs/metformin-er.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 185
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 13
    assert catalog['new-prescription-medications']['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (185, 13)
        assert status['next_candidate'] == 'new-prescription-medications'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
