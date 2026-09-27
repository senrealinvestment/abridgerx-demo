"""Vimovo approval criteria, indication gating, source notes and catalog mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/vimovo.json').read_text())
INDICATIONS = ['osteoarthritis', 'rheumatoid_arthritis', 'ankylosing_spondylitis']
STEP = 'failed_generic_nsaid_plus_ppi_one_month'
LETTER = 'letter_of_medical_necessity_submitted'
GATES = [STEP, LETTER]
FACTS = dict(indication=INDICATIONS[0], **dict.fromkeys(GATES, True))


@pytest.mark.parametrize('indication', INDICATIONS)
def test_approval(indication):
    result = evaluate(PACK, dict(FACTS, indication=indication))
    assert result.decision == 'pass'
    assert result.citations


@pytest.mark.parametrize('key', GATES)
@pytest.mark.parametrize('indication', INDICATIONS)
def test_each_required_gate(key, indication):
    result = evaluate(PACK, dict(FACTS, indication=indication, **{key: not FACTS[key]}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]
    assert result.failed_clauses[0]['citation'] == PACK['source']['citation']


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [False, True])
def test_unknown_is_not_absent(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('indication', ['gastric_ulcer', 'gastric_ulcer_risk_reduction', 'acute_pain', 'other', '', True, False])
def test_closed_indication(indication):
    result = evaluate(PACK, {'indication': indication})
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


def test_indication_first():
    assert evaluate(PACK, {}).missing_facts == ['indication']
    assert evaluate(PACK, {'indication': INDICATIONS[0]}).missing_facts == GATES


def test_ui_and_source():
    detail = drug_detail('vimovo')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    for key in GATES:
        assert PACK['fact_ui'][key]['when'] == {'fact': 'indication', 'in': INDICATIONS}
    ui_facts = {k: ('yes' if v else 'no') if isinstance(v, bool) else v for k, v in FACTS.items()}
    assert evaluate(PACK, _coerce_patient(ui_facts)).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'naproxen/esomeprazole magnesium'
    assert PACK['source']['effective_date'] == '2014-01-17'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for value in ['375mg-20mg', '500mg-20mg', '6 months', '30-day supply',
                  '2 doses/day', 'Version 1', '8/16/2013', '1/17/2014',
                  'acute pain', 'absorption is delayed', 'NSAID-associated gastric ulcers']:
        assert value in notes
    assert len(PACK['criteria']) == 3
    for clause in PACK['criteria'][1:]:
        assert clause['when'] == PACK['fact_ui'][clause['id']]['when']
    assert 'one month' in PACK['criteria'][1]['text']
    assert 'two separate medications' in PACK['criteria'][2]['text']
    assert 'treatment failure' in PACK['criteria'][2]['text']
    source = json.loads((BASE / 'criteria_text/vimovo.json').read_text())
    assert PACK['source']['effective_date'] == source['effective_date']
    assert PACK['source']['citation'] == source['source_url']


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['vimovo'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'vimovo.json').read_bytes() == (BASE / 'rule_packs/vimovo.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 180
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 18
    assert catalog['brand-name-multisource-medications']['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (180, 18)
        assert status['next_candidate'] == 'brand-name-multisource-medications'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
