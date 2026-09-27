"""Viberzi source criteria, clinical exclusions, UI, and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/viberzi.json').read_text())
GOOD = dict(
    indication='ibs_d', age_years=18,
    no_concomitant_opioids_or_benzodiazepine=True,
    failed_tca_or_ssri_8_weeks=True, failed_antispasmodic=True,
    failed_antidiarrheal=True, hypersensitivity_contraindication_or_intolerance=False,
    biliary_obstruction_or_sphincter_of_oddi_dysfunction=False,
    no_gallbladder=False, severe_hepatic_impairment=False,
    history_of_severe_constipation=False,
    alcohol_history_or_more_than_three_drinks_daily=False,
    pancreatitis_history_or_structural_pancreatic_disease=False,
)


def test_eligible():
    assert evaluate(PACK, GOOD).decision == 'pass'


@pytest.mark.parametrize('fact', GOOD)
@pytest.mark.parametrize('null', [False, True])
def test_missing(fact, null):
    patient = GOOD.copy()
    if null:
        patient[fact] = None
    else:
        del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('fact', [k for k, v in GOOD.items() if isinstance(v, bool)])
def test_each_approval_and_denial(fact):
    result = evaluate(PACK, dict(GOOD, **{fact: not GOOD[fact]}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [fact]
    assert result.citations == [PACK['source']['citation']]


@pytest.mark.parametrize('value', ['other', 'ibs_c', 'ibs', 'yes', True, False])
def test_closed_indication(value):
    assert evaluate(PACK, dict(GOOD, indication=value)).decision == 'fail'


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (17.99, 'fail'), (18, 'pass'), (90, 'pass')])
def test_age(age, decision):
    assert evaluate(PACK, dict(GOOD, age_years=age)).decision == decision


def test_ui():
    fields = {f['key']: f for f in drug_detail('viberzi')['fact_fields']}
    assert set(fields) == set(GOOD)
    assert fields['indication']['options'] == [dict(value='ibs_d', label='Irritable bowel syndrome with diarrhea (IBS-D)')]
    for fact, field in fields.items():
        assert field['type'] == 'select'
        if fact != 'indication':
            assert field['when'] == dict(fact='indication', eq='ibs_d')
        for option in field['options']:
            patient = _coerce_patient(dict(GOOD, **{fact: option['value']}))
            expected = patient[fact] == GOOD[fact]
            assert evaluate(PACK, patient).decision == ('pass' if expected else 'fail')


def test_metadata_and_notes():
    assert PACK['drug']['generic_name'] == 'eluxadoline'
    assert PACK['source']['effective_date'] == '2018-01-01'
    assert len(PACK['criteria']) == 13
    assert {f for c in PACK['criteria'] for f in c['required_facts']} == set(GOOD)
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for phrase in ['Version 1', '8/06/2018', '9/21/2018', 'metadata stub',
                   '3 months', '12 months', 'improvement', '60 tablets of 75 mg',
                   '60 tablets of 100 mg', 'pancreatitis', 'sphincter of Oddi spasm',
                   'severe constipation', 'mu-opioid receptor agonist']:
        assert phrase in notes
    assert 'trialed at least one TCA or SSRI for 8 weeks' in PACK['fact_ui']['failed_tca_or_ssri_8_weeks']['label']
    assert 'more than 3' in PACK['fact_ui']['alcohol_history_or_more_than_three_drinks_daily']['label']


def test_catalog():
    assert PACK['encoding_status'] == 'partial'
    assert (BASE/'viberzi.json').read_bytes() == (BASE/'rule_packs/viberzi.json').read_bytes()
    catalog = json.loads((BASE/'rule_packs_all.json').read_text())
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE/'rule_packs').glob('*.json')}
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 184
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 14
    for root in (BASE, BASE.parent):
        status = json.loads((root/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (184, 14, 'h-pylori-kits')
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status'] == 'partial')
    for ext in ('json', 'md'):
        assert (BASE/f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent/f'ENCODING_STATUS.{ext}').read_bytes()
    assert catalog['h-pylori-kits']['encoding_status'] == 'text_only'
    assert catalog['h-pylori-kits']['criteria'] == []
