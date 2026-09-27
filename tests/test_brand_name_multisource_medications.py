"""DAW policy conjunction, closed request scope, UI and catalog integrity."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail

BASE = ROOT / 'data/alaska/parsed'
SLUG = 'brand-name-multisource-medications'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
INDICATION = 'brand_multisource_daw_request'
GATES = ['tried_two_generic_manufacturers_failed', 'medwatch_and_lmn_submitted']
FACTS = dict(indication=INDICATION, **dict.fromkeys(GATES, True))


def test_approval():
    result = evaluate(PACK, FACTS)
    assert result.decision == 'pass'
    assert result.citations


@pytest.mark.parametrize('key', GATES)
def test_each_condition_required(key):
    result = evaluate(PACK, dict(FACTS, **{key: False}))
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


@pytest.mark.parametrize('indication', ['other', 'diabetes', '', True, False])
def test_closed_request(indication):
    result = evaluate(PACK, {'indication': indication})
    assert result.decision == 'fail'
    assert result.missing_facts == []


def test_gating():
    assert evaluate(PACK, {}).missing_facts == ['indication']
    assert evaluate(PACK, {'indication': INDICATION}).missing_facts == GATES
    assert evaluate(PACK, dict.fromkeys(GATES, True)).decision == 'need_info'


def test_ui_and_source_fidelity():
    detail = drug_detail(SLUG)
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert PACK['fact_ui']['indication']['options'][0]['value'] == INDICATION
    for key in GATES:
        assert fields[key]['when'] == {'fact': 'indication', 'eq': INDICATION}
    ui = dict(indication=INDICATION, **dict.fromkeys(GATES, 'yes'))
    assert evaluate(PACK, _coerce_patient(ui)).decision == 'pass'
    for key in GATES:
        assert evaluate(PACK, _coerce_patient(dict(ui, **{key: 'no'}))).decision == 'fail'
    assert len(PACK['criteria']) == 3
    assert 'inferred_required_facts' not in PACK
    assert PACK['encoding_status'] == 'partial'
    assert PACK['requires_pa'] is True
    notes = ' '.join(PACK['notes'])
    for term in ['Digoxin', 'Levothyroxine', 'Phenytoin', 'Warfarin', 'Orange Book', 'Version 1', '1/21/2011', '6/8/2012', 'DAW']:
        assert term in notes
    for term in ['same dose and interval', 'at least two different manufacturers', 'each product']:
        assert term in PACK['criteria'][1]['text']
    for term in ['each adverse', 'completed FDA MedWatch', 'letter of medical necessity', 'prescriber']:
        assert term in PACK['criteria'][2]['text']
    source = json.loads((BASE / 'criteria_text' / f'{SLUG}.json').read_text())
    assert PACK['source']['citation'] == source['source_url']


def test_catalog_and_mirrors():
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog[SLUG] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
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
