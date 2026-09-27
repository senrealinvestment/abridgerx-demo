"""Veozah approval gates, denial thresholds, source notes and catalog mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/veozah.json').read_text())
FACTS = dict(indication='moderate_to_severe_vasomotor_symptoms_due_to_menopause',
             fda_labeled_age='attested', baseline_lfts='performed', follow_up_lfts='attested',
             prior_therapy='failed_hormone_agent', cirrhosis='absent',
             severe_renal_impairment_or_esrd='absent', baseline_total_bilirubin='below_2x_uln',
             baseline_alt='below_2x_uln', baseline_ast='below_2x_uln')


@pytest.mark.parametrize('key', FACTS)
def test_closed_gates(key):
    clause = next(c for c in PACK['criteria'] if c['id'] == key)
    allowed = clause['predicate']['values']
    for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['other', 'yes', 'no', True, False]:
        result = evaluate(PACK, dict(FACTS, **{key: value}))
        assert result.decision == ('pass' if value in allowed else 'fail')
        assert [c['id'] for c in result.failed_clauses] == ([] if value in allowed else [key])
        assert result.citations


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [False, True])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('therapy', ['failed_hormone_agent', 'failed_non_hormone_agent', 'contraindicated_to_both'])
@pytest.mark.parametrize('denial', ['cirrhosis', 'severe_renal_impairment_or_esrd', 'baseline_total_bilirubin', 'baseline_alt', 'baseline_ast'])
def test_denials_override_each_therapy_route(therapy, denial):
    facts = dict(FACTS, prior_therapy=therapy)
    assert evaluate(PACK, facts).decision == 'pass'
    facts[denial] = 'at_2x_uln' if denial.startswith('baseline_') else 'present'
    assert evaluate(PACK, facts).decision == 'fail'


def test_ui_and_source_metadata():
    detail = drug_detail('veozah')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert len(fields['indication']['options']) == 1
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert evaluate(PACK, _coerce_patient(FACTS)).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'fezolinetant'
    assert PACK['drug']['therapeutic_class'] == 'nk3-receptor-antagonist'
    assert PACK['source']['effective_date'] == '2024-11-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    assert 'age_years' not in fields
    for text in ['>3× ULN', 'CYP1A2', '3 months', '12 months', '34 tablets for 34 days', 'manual review']:
        assert text in ' '.join(PACK['notes'])


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['veozah'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'veozah.json').read_bytes() == (BASE / 'rule_packs/veozah.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 148
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 50
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (148, 50)
        assert status['next_candidate'] == 'human-chorionic-gonadotropin'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
