"""Alaska Rhapsido closed gates, exceptions, notes and catalog mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/rhapsido.json').read_text())
FACTS = dict(indication='chronic_spontaneous_urticaria', age='at_least_18',
             prescriber_specialty='allergist', urticaria_duration='at_least_6_weeks',
             symptom_frequency='at_least_3_days_per_week',
             medication_review='evaluated_and_addressed',
             prior_h1_therapy='failed_max_dose_at_least_60_days', concomitant_biologic='absent')


@pytest.mark.parametrize('clause', PACK['criteria'])
def test_closed_gates(clause):
    key = clause['id']
    for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['yes', 'no', 'unknown', True, False]:
        result = evaluate(PACK, dict(FACTS, **{key: value}))
        allowed = value in clause['predicate']['values']
        assert result.decision == ('pass' if allowed else 'fail')
        assert [c['id'] for c in result.failed_clauses] == ([] if allowed else [key])
        assert result.citations


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert key in result.missing_facts


def test_contraindication_does_not_waive_symptom_criterion():
    facts = dict(FACTS, prior_h1_therapy='documented_clinical_contraindication')
    assert evaluate(PACK, facts).decision == 'pass'
    facts['symptom_frequency'] = 'not_on_max_dose'
    assert evaluate(PACK, facts).decision == 'fail'


def test_ui_metadata_and_notes():
    detail = drug_detail('rhapsido')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert len(fields['indication']['options']) == 1
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert evaluate(PACK, _coerce_patient(FACTS)).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'remibrutinib'
    assert PACK['drug']['therapeutic_class'] == 'btk-inhibitor'
    assert PACK['source']['effective_date'] == '2026-03-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['mucocutaneous', 'antithrombotic', 'CYP3A4 inhibitors or inducers',
                 'nasopharyngitis', 'bleeding', 'headache', 'nausea', 'abdominal pain',
                 '3 months', '1 year', '60 tablets per 30 days', 'manual review']:
        assert text in ' '.join(PACK['notes'])


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['rhapsido'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'rhapsido.json').read_bytes() == (BASE / 'rule_packs/rhapsido.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 140
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 58
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (140, 58)
        assert status['next_candidate'] == 'vesicular-monoamine'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
