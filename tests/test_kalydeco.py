"""Kalydeco initial eligibility, closed indication, UI, and catalog integration."""
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
IND = 'cystic_fibrosis_cftr_gating_or_r117h'
PATHS = ['fda_cleared_test_gating_mutations', 'fda_cleared_test_r117h',
         'prescriber_documentation_of_listed_mutation']
BOOLS = {'not_concomitant_strong_cyp3a_inducer',
         'no_strong_cyp3a_inhibitor_without_dose_adjustment', 'not_homozygous_f508del'}


def pack():
    return json.loads((BASE / 'rule_packs/kalydeco.json').read_text())


def base():
    return dict(indication=IND, age_years=2, cftr_mutation_confirmed=PATHS[0],
                **dict.fromkeys(BOOLS, True))


@pytest.mark.parametrize('confirmation', PATHS)
@pytest.mark.parametrize('age,expected', [(1, 'fail'), (1.99, 'fail'), (2, 'pass'), (80, 'pass')])
def test_confirmation_and_age(confirmation, age, expected):
    assert evaluate(pack(), dict(base(), cftr_mutation_confirmed=confirmation,
                                 age_years=age)).decision == expected


def test_missing_and_denials():
    for fact in base():
        for null in [False, True]:
            facts = base()
            if null:
                facts[fact] = None
            else:
                del facts[fact]
            result = evaluate(pack(), facts)
            assert result.decision == 'need_info'
            assert result.missing_facts == [fact]
    for fact in BOOLS:
        result = evaluate(pack(), dict(base(), **{fact: False}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [fact]
    for fact in ['indication', 'cftr_mutation_confirmed']:
        for value in ['other', 'not_met', 'yes', 'no', True, False]:
            assert evaluate(pack(), dict(base(), **{fact: value})).decision == 'fail'


def test_gating_and_select_coercion():
    p = pack()
    fields = {f['key']: f for f in drug_detail('kalydeco')['fact_fields']}
    assert set(fields) == set(base())
    for indication in [None, 'other']:
        facts = base()
        facts.pop('cftr_mutation_confirmed')
        facts['indication'] = indication
        result = evaluate(p, facts)
        assert 'cftr_mutation_confirmed' not in result.missing_facts
        assert result.decision == ('need_info' if indication is None else 'fail')
    passing = {'indication': {IND}, 'age_years': {'2'}, 'cftr_mutation_confirmed': set(PATHS)}
    for fact, field in fields.items():
        assert field['type'] == 'select' and field['free_text'] is False
        clause = next(c for c in p['criteria'] if c['required_facts'] == [fact])
        if fact == 'cftr_mutation_confirmed':
            assert field['when'] == clause['when'] == {'fact': 'indication', 'in': [IND]}
        else:
            assert 'when' not in field and 'when' not in clause
        for option in field['options']:
            value = option['value']
            result = evaluate(p, _coerce_patient(dict(base(), **{fact: value})))
            assert result.decision == ('pass' if value in passing.get(fact, {'yes'}) else 'fail')
    assert {o['value'] for o in fields['cftr_mutation_confirmed']['options']} == set(PATHS) | {'not_met'}
    assert {o['value'] for o in fields['indication']['options']} == {IND}


def test_metadata_notes_and_bundles():
    p = pack()
    assert p['drug'] == dict(name='Kalydeco', generic_name='ivacaftor', therapeutic_class='cystic-fibrosis')
    assert p['source']['effective_date'] == '2016-10-03'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/3bbljsga/ccfu_cf_kalydeco_20161003.pdf'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial' and len(p['criteria']) == 6
    assert 'inferred_required_facts' not in p and p['max_units'] is None
    notes = ' '.join(p['notes'])
    for term in ['Version 3', '5/31/2016', '10/3/2016', '3 months', 'month 3',
                 '6 more months', 'month 9', '1 year', 'no detriment or harm',
                 'clinical stabilization', 'clinical improvement', 'maximum 2 tablets or granule packets',
                 'manual review', 'Bidirectional sequencing', 'G551D', 'G1244E', 'G1349D',
                 'G178R', 'G551S', 'S1251N', 'S1255P', 'S549N', 'S549R', 'R117H']:
        assert term in notes
    assert (BASE / 'kalydeco.json').read_bytes() == (BASE / 'rule_packs/kalydeco.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['kalydeco'] == p
    assert p['alternatives'] == ['orkambi']
    assert catalog['orkambi']['alternatives'] == ['kalydeco']
    assert catalog['orkambi']['encoding_status'] == 'partial'
    assert len(catalog['orkambi']['criteria']) == 6
    result = evaluate(catalog['orkambi'], base())
    assert result.decision == 'need_info'
    assert 'indication_fda_labeled' in [c['id'] for c in result.failed_clauses]
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 162
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 36
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (162, 36)
    assert status['next_candidate'] == 'symproic'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
