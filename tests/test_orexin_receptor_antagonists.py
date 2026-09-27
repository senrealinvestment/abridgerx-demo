"""Orexin antagonist shared approval gates, explicit exclusions, and catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/orexin-receptor-antagonists.json').read_text())
APPROVAL = ['other_causes_ruled_out', 'two_prescription_sleep_aids_failed',
            'cbt_trial_documented', 'cbt_sleep_hygiene_education', 'cbt_misconception_counseling']
DENIAL = ['narcolepsy', 'concurrent_sedative_hypnotic']
FACTS = dict(indication='insomnia_sleep_onset_or_maintenance', age_years=18,
             medication_sleep_disturbance_addressed='ruled_out',
             **dict.fromkeys(APPROVAL, True), **dict.fromkeys(DENIAL, False))


@pytest.mark.parametrize('product', ['belsomra', 'dayvigo', 'quviviq', None])
@pytest.mark.parametrize('addressed', ['ruled_out', 'causative_medications_discontinued', 'causative_medications_adjusted'])
def test_shared_approval(product, addressed):
    facts = dict(FACTS, medication_sleep_disturbance_addressed=addressed)
    if product is not None:
        facts['product'] = product
    result = evaluate(PACK, facts)
    assert result.decision == 'pass'
    assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('key,value', [('age_years', 17), ('age_years', 17.99),
    ('medication_sleep_disturbance_addressed', 'not_addressed'),
    ('medication_sleep_disturbance_addressed', True)] +
    [(k, False) for k in APPROVAL] + [(k, True) for k in DENIAL])
def test_each_gate(key, value):
    result = evaluate(PACK, dict(FACTS, **{key: value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]


@pytest.mark.parametrize('value', ['other', 'narcolepsy', True, ''])
def test_closed_indication(value):
    assert evaluate(PACK, dict(FACTS, indication=value)).decision == 'fail'


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [False, True])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


def test_ui():
    detail = drug_detail('orexin-receptor-antagonists')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{key: value})))
            deny = ((key in DENIAL and value == 'yes') or
                    (key in APPROVAL and value == 'no') or value in ['17', 'not_addressed'])
            assert result.decision == ('fail' if deny else 'pass')


def test_metadata_and_manual_review():
    assert PACK['drug']['therapeutic_class'] == 'orexin-receptor-antagonist'
    assert PACK['source']['effective_date'] == '2022-06-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for text in ['Belsomra', 'suvorexant', 'Dayvigo', 'lemborexant', 'Quviviq', 'daridorexant',
                 'morning impairment', 'depression', 'suicidal ideation', 'sleep-driving',
                 'sleep paralysis', 'hallucinations', 'cataplexy-like', '3 months', '6 months',
                 '30 tablets per 30 days', 'manual review']:
        assert text in notes
    assert evaluate(PACK, dict(FACTS, requested_units=999, authorization_type='renewal')).decision == 'pass'
    assert evaluate(PACK, {}).decision == 'need_info'


def test_catalog():
    catalog = load_rule_pack_catalog()
    assert catalog['orexin-receptor-antagonists'] == PACK
    assert (BASE/'orexin-receptor-antagonists.json').read_bytes() == (BASE/'rule_packs/orexin-receptor-antagonists.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 156
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 42
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (156, 42)
        assert status['next_candidate'] == 'reclast'
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status']=='partial')
    for slug in ['reclast', 'atypical-antipsychotic-therapeutic-duplication']:
        assert catalog[slug]['encoding_status'] == 'text_only'
