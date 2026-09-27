"""Orkambi initial eligibility, interaction exceptions, UI and catalog integration."""
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
IND = 'cystic_fibrosis_homozygous_f508del'
PATHS = ['fda_cleared_cf_mutation_test_homozygous_f508del',
         'prescriber_documentation_of_homozygous_f508del']
INDUCERS = ['not_concomitant_strong_cyp3a_inducer', 'concomitant_with_dose_adjustment_of_inducer']
SUBSTRATES = ['not_concomitant_sensitive_or_narrow_ti_cyp3a_substrate',
              'concomitant_with_dose_adjustment_or_discontinuation']


def pack():
    return json.loads((BASE / 'rule_packs/orkambi.json').read_text())


def base():
    return dict(indication=IND, age_years=2, cf_diagnosis_with_positive_sweat_test=True,
                homozygous_f508del_confirmed=PATHS[0], cyp3a_inducer_status=INDUCERS[0],
                cyp3a_substrate_status=SUBSTRATES[0])


@pytest.mark.parametrize('confirmation', PATHS)
@pytest.mark.parametrize('inducer', INDUCERS)
@pytest.mark.parametrize('substrate', SUBSTRATES)
@pytest.mark.parametrize('age,expected', [(1, 'fail'), (1.99, 'fail'), (2, 'pass'), (80, 'pass')])
def test_approval_paths(confirmation, inducer, substrate, age, expected):
    facts = dict(base(), homozygous_f508del_confirmed=confirmation,
                 cyp3a_inducer_status=inducer, cyp3a_substrate_status=substrate, age_years=age)
    assert evaluate(pack(), facts).decision == expected


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
    for fact, value in [('cf_diagnosis_with_positive_sweat_test', False),
                        ('homozygous_f508del_confirmed', 'not_met'),
                        ('cyp3a_inducer_status', 'concomitant_without_adjustment'),
                        ('cyp3a_substrate_status', 'concomitant_without_adjustment')]:
        result = evaluate(pack(), dict(base(), **{fact: value}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [fact]
    for fact in ['indication', 'homozygous_f508del_confirmed',
                 'cyp3a_inducer_status', 'cyp3a_substrate_status']:
        for value in ['other', 'not_met', 'yes', 'no', True, False]:
            assert evaluate(pack(), dict(base(), **{fact: value})).decision == 'fail'


def test_gating_and_ui():
    p = pack()
    fields = {f['key']: f for f in drug_detail('orkambi')['fact_fields']}
    assert set(fields) == set(base())
    for indication in [None, 'other']:
        facts = base()
        facts.pop('homozygous_f508del_confirmed')
        facts['indication'] = indication
        result = evaluate(p, facts)
        assert 'homozygous_f508del_confirmed' not in result.missing_facts
        assert result.decision == ('need_info' if indication is None else 'fail')
    passing = {'indication': {IND}, 'age_years': {'2'},
               'homozygous_f508del_confirmed': set(PATHS),
               'cf_diagnosis_with_positive_sweat_test': {'yes'},
               'cyp3a_inducer_status': set(INDUCERS), 'cyp3a_substrate_status': set(SUBSTRATES)}
    for fact, field in fields.items():
        assert field['type'] == 'select' and field['free_text'] is False
        clause = next(c for c in p['criteria'] if c['required_facts'] == [fact])
        if fact == 'homozygous_f508del_confirmed':
            assert field['when'] == clause['when'] == {'fact': 'indication', 'in': [IND]}
        else:
            assert 'when' not in field and 'when' not in clause
        for option in field['options']:
            value = option['value']
            result = evaluate(p, _coerce_patient(dict(base(), **{fact: value})))
            assert result.decision == ('pass' if value in passing[fact] else 'fail')
    for fact, values in [('indication', {IND}), ('homozygous_f508del_confirmed', set(PATHS) | {'not_met'}),
                         ('cyp3a_inducer_status', set(INDUCERS) | {'concomitant_without_adjustment'}),
                         ('cyp3a_substrate_status', set(SUBSTRATES) | {'concomitant_without_adjustment'})]:
        assert {o['value'] for o in fields[fact]['options']} == values


def test_metadata_notes_and_bundles():
    p = pack()
    assert p['drug'] == dict(name='Orkambi', generic_name='lumacaftor/ivacaftor', therapeutic_class='cystic-fibrosis')
    assert p['source']['effective_date'] == '2019-06-10'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/okjkpt1d/20194ccfu_cf_orkambi_revised_20190419.pdf'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial' and len(p['criteria']) == 6
    assert 'inferred_required_facts' not in p and p['max_units'] is None
    notes = ' '.join(p['notes'])
    for term in ['Version 2', '5/31/2016', '4/19/2019', '06/10/2019', 'F580del', 'F508del',
                 '3 months', 'month 3', '6 more months', 'month 9', '1 year', 'no detriment or harm',
                 'clinical stabilization', 'clinical improvement', 'manual review',
                 'maximum 4 tablets/day', 'maximum 2 packets/day', '100/125', '200/125', '150/188',
                 'Mechanism', 'lumacaftor', 'ivacaftor', 'chloride transport']:
        assert term in notes
    assert (BASE / 'orkambi.json').read_bytes() == (BASE / 'rule_packs/orkambi.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['orkambi'] == p
    assert p['alternatives'] == ['kalydeco']
    assert catalog['kalydeco']['alternatives'] == ['orkambi']
    result = evaluate(catalog['kalydeco'], base())
    assert result.decision == 'need_info'
    assert 'indication_fda_labeled' in [c['id'] for c in result.failed_clauses]
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 147
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 51
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (147, 51)
    assert status['next_candidate'] == 'fentora'
    assert catalog['ofev']['encoding_status'] == 'partial'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
