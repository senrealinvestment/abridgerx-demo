"""Vecamyl closed indications, all approval gates, UI, source and mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/vecamyl.json').read_text())
INDICATIONS = ['essential_hypertension_moderate_severe', 'malignant_hypertension_uncomplicated']
EXCLUSIONS = ['coronary_insufficiency', 'recent_myocardial_infarction',
              'rising_or_elevated_bun_or_known_renal_insufficiency', 'uremia',
              'receiving_antibiotics_and_sulfonamides', 'glaucoma',
              'organic_pyloric_stenosis', 'hypersensitivity_to_mecamylamine']
STEP = 'failed_six_antihypertensive_classes_12_months'
FACTS = dict(indication=INDICATIONS[0], **{STEP: True}, **dict.fromkeys(EXCLUSIONS, False))


@pytest.mark.parametrize('indication', INDICATIONS)
def test_approval(indication):
    result = evaluate(PACK, dict(FACTS, indication=indication))
    assert result.decision == 'pass'
    assert result.citations


@pytest.mark.parametrize('key', [STEP] + EXCLUSIONS)
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


@pytest.mark.parametrize('indication', ['hypertension', 'essential_hypertension', 'other', '', True, False])
def test_closed_indication(indication):
    result = evaluate(PACK, {'indication': indication})
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


def test_indication_first():
    assert evaluate(PACK, {}).missing_facts == ['indication']
    assert evaluate(PACK, {'indication': INDICATIONS[0]}).missing_facts == [STEP] + EXCLUSIONS


def test_ui_and_source():
    detail = drug_detail('vecamyl')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    for key in [STEP] + EXCLUSIONS:
        assert PACK['fact_ui'][key]['when'] == {'fact': 'indication', 'in': INDICATIONS}
    ui_facts = {k: ('yes' if v else 'no') if isinstance(v, bool) else v for k, v in FACTS.items()}
    assert evaluate(PACK, _coerce_patient(ui_facts)).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'mecamylamine hcl'
    assert PACK['source']['effective_date'] == '1970-01-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for value in ['2.5 mg', '6 months', '30-day supply', '10 doses/day', 'Version 1', '1/02/2014', '1/17/2014']:
        assert value in notes
    assert len(PACK['criteria']) == 10
    step_text = next(c['text'] for c in PACK['criteria'] if c['id'] == STEP)
    for value in ['at least 6', '12 months', 'documented', 'blood pressure goals', 'maximum tolerated doses']:
        assert value in step_text


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['vecamyl'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'vecamyl.json').read_bytes() == (BASE / 'rule_packs/vecamyl.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 177
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 21
    assert catalog['narcan-nasal-spray-naloxone-opioid-overdose-treatment']['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (177, 21)
        assert status['next_candidate'] == 'narcan-nasal-spray-naloxone-opioid-overdose-treatment'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
