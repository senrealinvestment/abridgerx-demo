"""Sunosi closed indications, conditional airway therapy and MAOI exclusion."""
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
PACK = json.loads((BASE / 'rule_packs/sunosi.json').read_text())
FACTS = dict(age_years=18, indication='eds_associated_with_osa',
             prescriber_specialty='sleep_specialist', cpap_duration='treated_ge_90_days',
             cpap_continued='continued', narcolepsy_airway_obstruction='absent',
             wakefulness_promoting_step='modafinil_failed_ge_30_days',
             blood_pressure='well_controlled', maoi_within_14_days='absent')
INDICATIONS = ['eds_associated_with_narcolepsy', 'eds_associated_with_osa']

@pytest.mark.parametrize('indication', INDICATIONS)
def test_closed_gates(indication):
    facts = dict(FACTS, indication=indication)
    assert evaluate(PACK, facts).decision == 'pass'
    for clause in PACK['criteria']:
        key = clause['id']
        if clause.get('when', {}).get('eq', indication) != indication:
            continue
        if clause['predicate']['op'] != 'in':
            continue
        for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['other', 'yes', 'no', True, False]:
            result = evaluate(PACK, dict(facts, **{key: value}))
            allowed = value in clause['predicate']['values']
            assert result.decision == ('pass' if allowed else 'fail')
            assert [c['id'] for c in result.failed_clauses] == ([] if allowed else [key])
            assert clause['citation'] in result.citations

@pytest.mark.parametrize('indication', INDICATIONS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing_and_inapplicable(indication, omit):
    facts = dict(FACTS, indication=indication)
    for clause in PACK['criteria']:
        key = clause['id']
        changed = dict(facts, **{key: None})
        if omit:
            del changed[key]
        result = evaluate(PACK, changed)
        applies = clause.get('when', {}).get('eq', indication) == indication
        assert result.decision == ('need_info' if applies else 'pass')
        assert result.missing_facts == ([key] if applies else [])
        if not applies:
            assert evaluate(PACK, dict(facts, **{key: 'not_met'})).decision == 'pass'

@pytest.mark.parametrize('key,value,decision', [
    ('age_years',17,'fail'), ('age_years',17.99,'fail'), ('age_years',18,'pass'),
])
def test_numeric_boundaries(key, value, decision):
    assert evaluate(PACK, dict(FACTS, **{key:value})).decision == decision


def test_indication_missing_does_not_request_branch_facts():
    facts = {k:v for k,v in FACTS.items() if k not in ['indication','cpap_duration','cpap_continued','narcolepsy_airway_obstruction']}
    assert evaluate(PACK, facts).missing_facts == ['indication']


def test_ui_metadata_and_notes():
    fields = {f['key']: f for f in drug_detail('sunosi')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    for clause in PACK['criteria']:
        assert clause.get('when') == PACK['fact_ui'][clause['id']].get('when')
    assert evaluate(PACK, _coerce_patient(dict(FACTS, age_years='18'))).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'solriamfetol'
    assert PACK['drug']['therapeutic_class'] == 'dnri'
    assert PACK['source']['effective_date'] == '2019-11-20'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    for phrase in ['14 days','heart rate','blood pressure','serious heart problems','psychosis','bipolar','3 months','12 months','30 × 75mg','30 × 150mg','not indicated','manual review']:
        assert phrase in ' '.join(PACK['notes'])


def test_catalog_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['sunosi'] == PACK
    assert catalog['inhaled-prostacycline-mimetic']['encoding_status'] == 'text_only'
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 126
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 72
    assert (BASE/'sunosi.json').read_bytes() == (BASE/'rule_packs/sunosi.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (126,72)
    assert status['next_candidate'] == 'inhaled-prostacycline-mimetic'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
