"""New-product approval paths, reformulation threshold, UI gating and catalog."""
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
SLUG = 'new-prescription-medications'
PACK = json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())
PATHS = {
    'no_other_approved_therapy': {'no_other_approved_therapy': True},
    'failed_one_other_therapy': {'failed_one_other_therapy': True, 'is_reformulation_variant': False},
    'failed_two_other_therapies_reformulation': {'is_reformulation_variant': True, 'failed_two_other_therapies': True},
}


@pytest.mark.parametrize('path', PATHS)
def test_paths_and_each_required_attestation(path):
    facts = dict(PATHS[path], indication=path)
    assert evaluate(PACK, facts).decision == 'pass'
    for key in PATHS[path]:
        result = evaluate(PACK, dict(facts, **{key: not facts[key]}))
        assert result.decision == 'fail'
        assert result.citations == [PACK['source']['citation']]
        for omit in [False, True]:
            missing = dict(facts, **{key: None})
            if omit:
                del missing[key]
            result = evaluate(PACK, missing)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
    # Stale answers from other paths must not interfere.
    stale = {key: False for branch in PATHS.values() for key in branch if key not in facts}
    assert evaluate(PACK, dict(stale, **facts)).decision == 'pass'


@pytest.mark.parametrize('path', ['other', '', True, False, 'follows_like_drug_pa_guidelines'])
def test_closed_paths(path):
    result = evaluate(PACK, {'indication': path})
    assert result.decision == 'fail'
    assert result.missing_facts == []


def test_path_required_and_reformulation_cannot_use_one_failure():
    for facts in [{}, {'indication': None}]:
        result = evaluate(PACK, facts)
        assert result.decision == 'need_info'
        assert result.missing_facts == ['indication']
    assert evaluate(PACK, dict(indication='failed_one_other_therapy',
                             failed_one_other_therapy=True, is_reformulation_variant=True)).decision == 'fail'
    result = evaluate(PACK, dict(indication='failed_two_other_therapies_reformulation',
                                is_reformulation_variant=True, failed_one_other_therapy=True))
    assert result.decision == 'need_info'
    assert result.missing_facts == ['failed_two_other_therapies']


def test_ui_gating_and_coercion():
    detail = drug_detail(SLUG)
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    assert [o['value'] for o in fields['indication']['options']] == list(PATHS)
    for key, field in fields.items():
        assert field['type'] == 'select'
        assert field['options'] == PACK['fact_ui'][key]['options']
        assert field.get('when') == PACK['fact_ui'][key].get('when')
        if key != 'indication':
            assert field['when']['in'] == [p for p, facts in PATHS.items() if key in facts]
    for path, facts in PATHS.items():
        raw = dict(indication=path, **{k: 'yes' if v else 'no' for k, v in facts.items()})
        assert evaluate(PACK, _coerce_patient(raw)).decision == 'pass'
    for clause in PACK['criteria'][1:]:
        assert len(clause['when']['in']) == 1
        assert clause['when']['in'][0] in PATHS


def test_source_and_notes_boundaries():
    source = json.loads((BASE / 'criteria_text' / f'{SLUG}.json').read_text())
    assert PACK['source']['citation'] == source['source_url']
    assert PACK['source']['effective_date'] == '2022-11-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['requires_pa'] is True
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert len(PACK['criteria']) == 6
    notes = ' '.join(PACK['notes'])
    for term in ['Version 1', '04/16/2010', '10/8/2020', '11/20/2020', 'A-rated',
                 'six (6) months', 'DUR', 'P&T', 'preferred-class', '12 months',
                 '30-day', 'Orange Book', 'same pharmacologic mechanism',
                 'dosage form', 'release mechanism', 'route', 'racemic mixture',
                 'enantiomer', 'diastereomer', 'isomer', 'prodrug', 'active metabolite']:
        assert term in notes


def test_catalog_and_mirrors():
    catalog = json.loads((BASE / 'rule_packs_all.json').read_text())
    assert catalog[SLUG] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 190
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 8
    assert catalog['hemophilia']['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (190, 8)
        assert status['next_candidate'] == None
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
