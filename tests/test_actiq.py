"""Actiq Alaska Medicaid Version 2 criteria, UI and catalog regression checks."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
ATC = 'already_receiving_around_the_clock_opioid_for_cancer_pain'
TOL = 'opioid_tolerant_for_persistent_cancer_pain'


def pack():
    return json.loads((BASE / 'rule_packs/actiq.json').read_text())


def facts(**extra):
    return dict({'indication': 'cancer_breakthrough_pain', 'age_years': 16,
                 ATC: True, TOL: True}, **extra)


def test_age_boundary():
    for age in [16, 17, 18, 65]:
        assert evaluate(pack(), facts(age_years=age)).decision == 'pass'
    for age in [0, 15, 15.9]:
        result = evaluate(pack(), facts(age_years=age))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['minimum_age']


def test_closed_indication():
    for invalid in ['yes', 'no', 'unknown', True, False, 'cancer_pain', 'non_cancer_pain']:
        result = evaluate(pack(), facts(indication=invalid))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['indication_fda_labeled']


def test_required_attestations_and_missing_facts():
    for fact in [ATC, TOL]:
        result = evaluate(pack(), facts(**{fact: False}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [fact]
    for fact in facts():
        patient = facts()
        del patient[fact]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [fact]
    result = evaluate(pack(), {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(facts())


def test_ui_closed_selects_and_coercion():
    detail = drug_detail('actiq')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    for field in fields.values():
        assert field['type'] == 'select'
        assert not field.get('free_text')
    assert fields['indication']['options'] == pack()['fact_ui']['indication']['options']
    assert [o['value'] for o in fields['indication']['options']] == ['cancer_breakthrough_pain']
    assert fields['age_years']['options'] == [
        {'value': '0', 'label': 'Under 16 years'},
        {'value': '16', 'label': '16 years or older'},
    ]
    for fact in [ATC, TOL]:
        assert fields[fact]['options'] == [
            {'value': 'yes', 'label': 'Yes'}, {'value': 'no', 'label': 'No'},
        ]
    patient = {'indication': 'cancer_breakthrough_pain', 'age_years': '16', ATC: 'yes', TOL: 'yes'}
    assert evaluate(pack(), _coerce_patient(patient)).decision == 'pass'
    for fact, value in [('age_years', '0'), (ATC, 'no'), (TOL, 'no')]:
        assert evaluate(pack(), _coerce_patient(dict(patient, **{fact: value}))).decision == 'fail'


def test_metadata_and_notes_only_gaps():
    p = pack()
    assert p['drug'] == {'name': 'Actiq', 'generic_name': 'fentanyl citrate, oral transmucosal',
                         'therapeutic_class': 'analgesics-opioid-reversal-agents'}
    assert p['source']['effective_date'] == '2014-09-19'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/eujlbouj/actiq.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/actiq.pdf'
    assert p['encoding_status'] == 'partial'
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 4
    assert {c['predicate']['fact'] for c in p['criteria']} == set(facts())
    assert p['criteria'][1]['predicate'] == {'op': 'gte', 'fact': 'age_years', 'value': 16}
    assert p['max_units']['quantity'] is None
    assert '3 per day' in p['max_units']['notes']
    notes = ' '.join(p['notes'])
    for text in ['Version 2', '09/19/2014', '09/19/2008', 'December 2011',
                 'criterion 1', 'closed cancer breakthrough pain indication',
                 'TIRF', 'outpatients', 'up to 6 months', '3 per day']:
        assert text in notes
    assert p['alternatives'] == []


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('actiq') == ('actiq', pack())
    assert (BASE / 'actiq.json').read_bytes() == (BASE / 'rule_packs/actiq.json').read_bytes()
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 83
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 115
    for slug in ['atypical-antipsychotic-therapeutic-duplication', 'fentora', 'subsys']:
        assert catalog[slug]['encoding_status'] == 'text_only'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 83 and status['encoding_text_only'] == 115
    assert status['next_candidate'] == 'krystexxa'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
