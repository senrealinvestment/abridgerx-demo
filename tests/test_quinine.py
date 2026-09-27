"""Quinine's closed indication, source limits and catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/quinine.json').read_text())


def test_approved_indication():
    result = evaluate(PACK, _coerce_patient({'indication': 'uncomplicated_p_falciparum_malaria'}))
    assert result.decision == 'pass'
    assert result.citations == [PACK['source']['citation']]
    assert any('60 days' in note for note in result.notes)


@pytest.mark.parametrize('indication', [
    'severe_malaria', 'complicated_malaria', 'malaria_prevention',
    'nocturnal_leg_cramps_treatment', 'nocturnal_leg_cramps_prevention',
    'other', 'unapproved_condition', 'uncomplicated_p_vivax_malaria',
])
def test_unapproved_indications(indication):
    result = evaluate(PACK, {'indication': indication})
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


@pytest.mark.parametrize('facts', [{}, {'indication': None}])
def test_missing_indication(facts):
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == ['indication']


def test_ui_and_metadata():
    detail = drug_detail('quinine')
    assert detail['can_evaluate']
    assert [f['key'] for f in detail['fact_fields']] == ['indication']
    assert detail['fact_fields'][0]['type'] == 'select'
    for option in PACK['fact_ui']['indication']['options']:
        expected = 'pass' if option['value'] == 'uncomplicated_p_falciparum_malaria' else 'fail'
        assert evaluate(PACK, {'indication': option['value']}).decision == expected
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2009-01-01'
    assert PACK['max_units'] is None
    notes = ' '.join(PACK['notes'])
    for phrase in ['powder', 'Qualaquin 324 mg capsule', '06/05/2009', '60 days', 'manual review']:
        assert phrase in notes
    assert (BASE / 'quinine.json').read_bytes() == (BASE / 'rule_packs/quinine.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['quinine'] == PACK
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 174
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 24
    assert catalog['rybix-odt']['encoding_status'] == 'text_only'
