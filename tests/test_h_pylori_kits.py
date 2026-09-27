"""H. pylori kit diagnosis, diagnostic confirmation, UI and source boundaries."""
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
PACK = json.loads((BASE / 'rule_packs/h-pylori-kits.json').read_text())
IND = 'h_pylori_with_duodenal_ulcer_disease'
FACT = 'positive_h_pylori_diagnostic_test'


def test_approval_and_missing_information():
    facts = {'indication': IND, FACT: True}
    assert evaluate(PACK, facts).decision == 'pass'
    assert evaluate(PACK, {}).missing_facts == ['indication']
    for key in facts:
        for value in [None, 'omit']:
            patient = dict(facts, **{key: value})
            if value == 'omit':
                del patient[key]
            result = evaluate(PACK, patient)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
    result = evaluate(PACK, dict(facts, **{FACT: False}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [FACT]
    assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('indication', ['other', '', True, False, 'h_pylori_infection'])
def test_closed_indication(indication):
    result = evaluate(PACK, {'indication': indication})
    assert result.decision == 'fail'
    assert result.missing_facts == []


def test_ui_gating_and_coercion():
    detail = drug_detail('h-pylori-kits')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == {'indication', FACT}
    assert [o['value'] for o in fields['indication']['options']] == [IND]
    assert fields[FACT]['when'] == PACK['criteria'][1]['when'] == {'fact': 'indication', 'in': [IND]}
    for answer, decision in [('yes', 'pass'), ('no', 'fail')]:
        assert evaluate(PACK, _coerce_patient({'indication': IND, FACT: answer})).decision == decision


def test_source_and_notes_only_boundaries():
    source = json.loads((BASE / 'criteria_text/h-pylori-kits.json').read_text())
    assert PACK['source']['citation'] == source['source_url']
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '1970-01-01'
    assert PACK['requires_pa'] is True
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert len(PACK['criteria']) == 2
    notes = ' '.join(PACK['notes'])
    for term in ['Helidac 224', 'Pylera 120', 'Prevpac 112', 'Omeclamox-Pak 80',
                 'H2 antagonist', 'past 5 years', 'one-year', 'References',
                 'Version 1', '12/24/2012', '01/18/2013', 'one pre-packaged therapy']:
        assert term in notes


def test_catalog_and_mirrors():
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog['h-pylori-kits'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'h-pylori-kits.json').read_bytes() == (BASE / 'rule_packs/h-pylori-kits.json').read_bytes()
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 187
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 11
    assert catalog['genotypes']['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (187, 11)
        assert status['next_candidate'] == 'genotypes'
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
