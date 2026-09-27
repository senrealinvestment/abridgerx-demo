"""Reyvow: seven approval gates, closed acute indication, notes-only cautions."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/alaska/parsed'
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog


def pack():
    return json.loads((BASE / 'rule_packs/reyvow.json').read_text())


def facts():
    return dict(indication='migraine_with_or_without_aura', age_years=18,
                prescriber_specialty='neurologist', medication_overuse_ruled_out=True,
                failed_one_prophylactic_ge_2mo='one_prophylactic_ge_2mo',
                failed_two_triptans_or_contraindicated='two_different_triptans_failed',
                agrees_no_driving_or_machinery_ge_8_hours=True)


def test_approval_missing_and_every_ui_option():
    p = pack()
    assert evaluate(p, facts()).decision == 'pass'
    assert set(evaluate(p, {}).missing_facts) == set(facts())
    for key in facts():
        patient = facts()
        del patient[key]
        result = evaluate(p, patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
        for option in p['fact_ui'][key]['options']:
            value = option['value']
            result = evaluate(p, _coerce_patient(dict(facts(), **{key: value})))
            fails = value in ['false', 'not_met', '0']
            assert result.decision == ('fail' if fails else 'pass'), (key, value)
            if fails:
                assert [c['id'] for c in result.failed_clauses] == [key]
                assert result.citations == [p['source']['citation']]


@pytest.mark.parametrize('value', ['migraine_prevention', 'migraine_acute', 'other', True, False, 'yes'])
def test_closed_indication(value):
    result = evaluate(pack(), dict(facts(), indication=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


@pytest.mark.parametrize('age,decision', [(17, 'fail'), (18, 'pass'), (19, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(pack(), dict(facts(), age_years=age)).decision == decision


def test_ui_metadata_notes_and_no_added_denials():
    p = pack()
    fields = {f['key']: f for f in drug_detail('reyvow')['fact_fields']}
    assert set(fields) == set(facts())
    assert len(p['criteria']) == 7
    for c in p['criteria']:
        assert c['citation'] == p['source']['citation']
        assert fields[c['id']]['option_source'] == ('age_bands' if c['id'] == 'age_years' else 'fact_ui')
        assert 'when' not in c
    assert p['drug']['generic_name'] == 'lasmiditan'
    assert p['drug']['therapeutic_class'] == '5ht1f-agonist'
    assert p['source']['effective_date'] == '2021-01-11'
    assert p['encoding_status'] == 'partial'
    assert p['max_units'] is None
    assert 'inferred_required_facts' not in p
    for phrase in ['preventive', 'beta blockers', '2 months', '8 hours', '24 hours',
                   'CNS depression', 'alcohol', 'serotonin syndrome', 'severe hepatic',
                   'fetal harm', '3 months', '12 months', '50mg', '100mg', '8 per 30 days']:
        assert phrase in ' '.join(p['notes'])
    assert evaluate(p, dict(facts(), severe_hepatic_impairment=True,
                           pregnant=True, quantity=100)).decision == 'pass'


def test_catalog_mirrors_and_scope():
    p = pack()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('reyvow') == ('reyvow', p)
    assert (BASE/'reyvow.json').read_bytes() == (BASE/'rule_packs/reyvow.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE/'rule_packs').glob('*.json')}
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 187
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 11
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (187, 11)
    assert status['next_candidate'] == 'genotypes'
    assert catalog['bone-resorption-inhibitors']['encoding_status'] == 'partial'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status']=='partial')
    for ext in ('json', 'md'):
        assert (BASE/f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent/f'ENCODING_STATUS.{ext}').read_bytes()
