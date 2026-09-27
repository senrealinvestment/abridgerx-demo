"""Xcopri eligibility, dose boundary, UI, and synchronized catalog regression."""
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
PACK = json.loads((BASE / 'rule_packs/xcopri.json').read_text())
FACTS = dict(age_years=18, indication='partial_onset_seizures',
             prescriber_specialty='neurologist', qualifying_anticonvulsants_count=2,
             familial_short_qt_syndrome='absent', daily_dose_mg=400)


def test_closed_choices_and_ui():
    assert evaluate(PACK, FACTS).decision == 'pass'
    fields = {f['key']: f for f in drug_detail('xcopri')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert [o['value'] for o in fields['indication']['options']] == ['partial_onset_seizures']
    for clause in PACK['criteria']:
        key = clause['id']
        assert fields[key]['type'] == 'select' and not fields[key].get('free_text')
        for option in fields[key]['options']:
            facts = _coerce_patient(dict(FACTS, **{key: option['value']}))
            result = evaluate(PACK, facts)
            assert result.decision in ['pass', 'fail']
            assert clause['citation'] in result.citations
        if clause['predicate']['op'] == 'in':
            for value in [o['value'] for o in fields[key]['options']] + ['other', 'yes', 'no', True, False]:
                result = evaluate(PACK, dict(FACTS, **{key: value}))
                allowed = value in clause['predicate']['values']
                assert result.decision == ('pass' if allowed else 'fail')
                assert [c['id'] for c in result.failed_clauses] == ([] if allowed else [key])
    assert evaluate(PACK, _coerce_patient({k: str(v) for k, v in FACTS.items()})).decision == 'pass'


@pytest.mark.parametrize('key,value,decision', [
    ('age_years', 17.99, 'fail'), ('age_years', 18, 'pass'), ('age_years', 80, 'pass'),
    ('qualifying_anticonvulsants_count', 0, 'fail'),
    ('qualifying_anticonvulsants_count', 1, 'fail'),
    ('qualifying_anticonvulsants_count', 2, 'pass'),
    ('qualifying_anticonvulsants_count', 3, 'pass'),
    ('daily_dose_mg', 12.5, 'pass'), ('daily_dose_mg', 399, 'pass'),
    ('daily_dose_mg', 400, 'pass'), ('daily_dose_mg', 400.01, 'fail'),
    ('daily_dose_mg', 800, 'fail'), ('familial_short_qt_syndrome', 'present', 'fail'),
])
def test_boundaries_and_independent_denials(key, value, decision):
    result = evaluate(PACK, dict(FACTS, **{key: value}))
    assert result.decision == decision
    assert [c['id'] for c in result.failed_clauses] == ([key] if decision == 'fail' else [])


@pytest.mark.parametrize('key', list(FACTS))
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


def test_combined_denials():
    result = evaluate(PACK, dict(FACTS, familial_short_qt_syndrome='present', daily_dose_mg=401))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'familial_short_qt_syndrome', 'daily_dose_mg'}


def test_metadata_and_mirrors():
    assert PACK['drug'] == dict(name='Xcopri', generic_name='cenobamate', therapeutic_class='anticonvulsant')
    assert PACK['source']['effective_date'] == '2021-03-15'
    assert PACK['encoding_status'] == 'partial' and PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert len(PACK['criteria']) == 6
    for phrase in ['distinct', 'partial seizures', 'failed', 'contraindicated']:
        assert phrase in PACK['fact_ui']['qualifying_anticonvulsants_count']['label']
    for phrase in ['GABAa', 'dose adjustments', 'suicidal', 'somnolence', 'fatigue', 'CNS depressants', 'alcohol', 'contraceptive', '3 months', '12 months', '30 days', '400 mg/day', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])
    catalog = load_rule_pack_catalog()
    assert catalog['xcopri'] == PACK
    assert catalog['revatio']['encoding_status'] == 'partial'
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 168
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 30
    assert (BASE / 'xcopri.json').read_bytes() == (BASE / 'rule_packs/xcopri.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (168, 30)
    assert status['next_candidate'] == 'cialis'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
