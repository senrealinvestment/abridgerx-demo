"""Ztalmy source gates, closed indication, UI attestations, and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/ztalmy.json').read_text())
FACTS = dict(
    indication='cdkl5_deficiency_disorder_seizures', age_years=2,
    prescriber_specialty='neurologist_or_consult',
    pathogenic_cdkl5_mutation_confirmed=True, two_aed_requirement_met=True,
)


def test_eligible():
    assert evaluate(PACK, FACTS).decision == 'pass'


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['lennox_gastaut_syndrome', 'other', 'yes', 'no', True, False])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'indication'}


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (1.99, 'fail'), (2, 'pass'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


@pytest.mark.parametrize('fact', [f for f in FACTS if f not in {'age_years', 'indication'}])
def test_unmet_gate(fact):
    result = evaluate(PACK, dict(FACTS, **{fact: False}))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {fact}
    assert result.citations


def test_ui_options():
    fields = {f['key']: f for f in drug_detail('ztalmy')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == ['cdkl5_deficiency_disorder_seizures']
    assert all('when' not in c for c in PACK['criteria'])
    for fact, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{fact: value})))
            assert result.decision == ('fail' if value in {'no', '0', 'none'} else 'pass'), (fact, value)


@pytest.mark.parametrize('value', ['none', 'cardiologist', 'yes', True])
def test_unqualified_specialty(value):
    result = evaluate(PACK, dict(FACTS, prescriber_specialty=value))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'prescriber_specialty'}


def test_source_thresholds_and_notes():
    labels = ' '.join(c['text'] for c in PACK['criteria'])
    for phrase in ['in consultation', 'neurologist', 'genetically confirmed',
                   'pathogenic or likely pathogenic', 'CDKL5', 'tried and failed or is currently taking',
                   'at least two previous antiepileptic drugs']:
        assert phrase in labels
    for phrase in ['Version 1', '2/28/2023', '4/21/2023', '6/1/2023',
                   '3 months', '6 months', 'sustained reduction in monthly seizure frequency',
                   'pre-treatment baseline', '1800 mg (36 ml) daily', 'schedule V',
                   'suicidal', 'Withdraw gradually', 'status epilepticus', 'fetal harm', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])
    assert PACK['criteria'][0]['predicate'] == dict(op='in', fact='indication', values=['cdkl5_deficiency_disorder_seizures'])


def test_metadata_and_catalog():
    assert PACK['drug'] == dict(name='Ztalmy', generic_name='ganaxolone', therapeutic_class='antiepileptic')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2023-06-01'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/4vlf31zn/5biv-ztalmy_criteria_2023.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert len(PACK['criteria']) == 5
    assert 'inferred_required_facts' not in PACK
    assert (BASE / 'ztalmy.json').read_bytes() == (BASE / 'rule_packs/ztalmy.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 176
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 22
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (176, 22)
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'naloxone-opioid-overdose-treatment-evzio'
        assert catalog[status['next_candidate']]['encoding_status'] == 'text_only'
    assert (BASE / 'ENCODING_STATUS.md').read_bytes() == (BASE.parent / 'ENCODING_STATUS.md').read_bytes()

    assert catalog['crenessity']['encoding_status'] == 'partial'
    assert len(catalog['crenessity']['criteria']) == 7
