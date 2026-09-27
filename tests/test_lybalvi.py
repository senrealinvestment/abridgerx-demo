"""Lybalvi shared approval gates, explicit exclusions, and catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/lybalvi.json').read_text())
APPROVAL = ['psychiatrist_or_consultation', 'dsm5_diagnosis',
            'baseline_metabolic_panel_documented', 'ongoing_metabolic_monitoring',
            'adverse_effect_monitoring', 'two_atypical_antipsychotics_failed_4_weeks_each']
DENIAL = ['dementia_related_psychosis', 'using_opioids', 'acute_opioid_withdrawal',
          'strong_cyp3a4_inducer', 'levodopa_or_dopamine_agonist', 'recent_mi',
          'unstable_cardiovascular_disease']
FACTS = dict(indication='schizophrenia', age_years=18,
             **dict.fromkeys(APPROVAL, True), **dict.fromkeys(DENIAL, False))


@pytest.mark.parametrize('indication', ['schizophrenia', 'bipolar_i_disorder'])
def test_shared_approval(indication):
    result = evaluate(PACK, dict(FACTS, indication=indication))
    assert result.decision == 'pass'
    assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('indication', ['schizophrenia', 'bipolar_i_disorder'])
@pytest.mark.parametrize('key,value', [('age_years', 17), ('age_years', 17.99)] +
                         [(k, False) for k in APPROVAL] + [(k, True) for k in DENIAL])
def test_each_gate(indication, key, value):
    result = evaluate(PACK, dict(FACTS, indication=indication, **{key: value}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]


@pytest.mark.parametrize('value', ['other', 'bipolar_ii_disorder', True, ''])
def test_closed_indications(value):
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
    detail = drug_detail('lybalvi')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{key: value})))
            deny = (key in DENIAL and value == 'yes') or (key in APPROVAL and value == 'no') or value == '17'
            assert result.decision == ('fail' if deny else 'pass')


def test_metadata_and_manual_review():
    assert PACK['drug']['generic_name'] == 'olanzapine/samidorphan'
    assert PACK['drug']['therapeutic_class'] == 'atypical-antipsychotic-opioid-antagonist'
    assert PACK['source']['effective_date'] == '2022-01-04'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for text in ['lithium or valproate', 'maintenance monotherapy', 'package insert',
                 '3 months', '1 year', 'improvement and stabilization', 'severe metabolic',
                 'tardive dyskinesia', '30 tablets', '1 tablet per day', 'manual review']:
        assert text in notes
    assert evaluate(PACK, dict(FACTS, requested_units=999, authorization_type='renewal')).decision == 'pass'
    assert evaluate(PACK, {}).decision == 'need_info'


def test_catalog():
    catalog = load_rule_pack_catalog()
    assert catalog['lybalvi'] == PACK
    assert (BASE/'lybalvi.json').read_bytes() == (BASE/'rule_packs/lybalvi.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 198
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 0
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (198, 0)
        assert status['next_candidate'] == None
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status']=='partial')
    for slug in ['hemophilia', 'atypical-antipsychotic-therapeutic-duplication']:
        assert catalog[slug]['encoding_status'] == 'partial'
