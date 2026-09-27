"""HCV DAA initial eligibility, conditional attestations, and catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc.json').read_text())
IND = 'chronic_hepatitis_c'
NEXT = '2024-2025-season'
FACTS = [c['id'] for c in PACK['criteria'] if c['id'] not in ['indication', 'age_ge_12_or_pediatric_specialty']]


def patient():
    return dict(indication=IND, age_years=12, **dict.fromkeys(FACTS, True))


@pytest.mark.parametrize('fact', FACTS)
@pytest.mark.parametrize('value', [False, None, 'absent'])
def test_each_required_attestation(fact, value):
    p = patient()
    if value == 'absent':
        del p[fact]
    else:
        p[fact] = value
    r = evaluate(PACK, p)
    assert r.decision == ('fail' if value is False else 'need_info')
    assert r.missing_facts == ([] if value is False else [fact])
    assert [c['id'] for c in r.failed_clauses] == ([fact] if value is False else [])


@pytest.mark.parametrize('age,specialist,decision', [
    (2, True, 'fail'), (2, None, 'fail'), (3, True, 'pass'),
    (3, False, 'fail'), (3, None, 'need_info'), (6, True, 'pass'),
    (7, True, 'pass'), (11, False, 'fail'), (11, True, 'pass'),
    (12, None, 'pass'), (12, False, 'pass'), (65, None, 'pass'),
    (None, True, 'need_info'),
])
def test_age_boundary(age, specialist, decision):
    assert evaluate(PACK, {**patient(), 'age_years': age, 'pediatric_liver_specialist': specialist}).decision == decision


@pytest.mark.parametrize('indication', ['acute_hepatitis_c', 'other', '', None])
def test_closed_indication(indication):
    r = evaluate(PACK, {'indication': indication})
    assert r.decision == ('need_info' if indication is None else 'fail')
    assert r.missing_facts == (['indication'] if indication is None else [])


def test_ui():
    fields = {f['key']: f for f in drug_detail('hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc')['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    assert {o['value'] for o in fields['indication']['options']} == {IND, 'other'}
    for f in set(fields) - {'indication'}:
        assert fields[f]['when'] == {'fact': 'indication', 'eq': IND}
        assert fields[f]['option_source'] == 'fact_ui'
    p = _coerce_patient(dict(indication=IND, age_years='12', **dict.fromkeys(FACTS, 'yes')))
    assert evaluate(PACK, p).decision == 'pass'
    for f in FACTS:
        assert evaluate(PACK, {**p, **_coerce_patient({f: 'no'})}).decision == 'fail'


def test_artifacts_and_scope():
    assert PACK['encoding_status'] == 'partial'
    assert len(PACK['criteria']) == 16
    assert PACK['source']['effective_date'] == '2022-01-04'
    assert 'inferred_required_facts' not in PACK
    assert (BASE/'hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc.json').read_bytes() == (BASE/'rule_packs/hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc.json').read_bytes()
    catalog = json.loads((BASE/'rule_packs_all.json').read_text())
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE/'rule_packs').glob('*.json')}
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 189
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 9
    assert catalog[NEXT]['encoding_status'] == 'text_only'
    for filename in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE/filename).read_bytes() == (BASE.parent/filename).read_bytes()
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (189, 9, NEXT)
    assert status['partial_slugs'] == sorted(s for s,p in catalog.items() if p['encoding_status']=='partial')
    notes = ' '.join(PACK['notes'])
    for phrase in ['Tables 1a/1b', 'Table 2', 'non-preferred', 'do not require PA', '16 weeks', '<25 IU/mL', 'dispensing error', 'lost/stolen', '7 calendar days', 'ribavirin', '11/19/2021', '5/5/2022']:
        assert phrase.lower() in notes.lower()


def test_twin_parity_and_scope():
    twin = json.loads((BASE / 'rule_packs/genotypes.json').read_text())
    for key in ['criteria', 'fact_ui', 'requires_pa', 'pdl_status', 'alternatives']:
        assert PACK[key] == twin[key]
    assert PACK['drug']['name'] == 'Hepatitis C Direct Acting Antivirals for Chronic Hepatitis C Criteria - All Products'
    assert 'Twin slug genotypes' in ' '.join(PACK['notes'])
    assert PACK['source']['citation'] == twin['source']['citation']
    assert 'hepatitis-c-direct-acting-antivirals-for-chronic-hepatitis-c-criteria-all-produc' in ' '.join(twin['notes'])
    for slug in ['000-unit', '2024-2025-season']:
        assert json.loads((BASE / f'rule_packs/{slug}.json').read_text())['encoding_status'] == 'text_only'
