"""Cholbam's two indication paths, shared denials and catalog integration."""
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
BASD = 'bile_acid_synthesis_disorder_single_enzyme_defect'
PD = 'peroxisomal_disorder_zellweger_spectrum'
CONFIRMATIONS = {'abnormal_urinary_bile_acid_fab_ms', 'molecular_genetic_testing_consistent'}
SPECIALTIES = {'gastroenterologist', 'hepatologist', 'gastroenterologist_consult', 'hepatologist_consult'}
MANIFESTATIONS = 'exhibits_liver_disease_steatorrhea_or_fat_soluble_vitamin_complications'


def pack():
    return json.loads((BASE / 'rule_packs/cholbam.json').read_text())


def base(indication=BASD):
    facts = dict(indication=indication, prescriber_specialty='hepatologist',
                 baseline_liver_function_labs_documented=True,
                 no_complete_biliary_obstruction=True)
    if indication == BASD:
        facts['basd_confirmation'] = 'abnormal_urinary_bile_acid_fab_ms'
    else:
        facts.update({MANIFESTATIONS: True, 'cholbam_used_as_adjunctive_therapy': True})
    return facts


@pytest.mark.parametrize('indication', [BASD, PD])
def test_paths_and_missing_facts(indication):
    p = pack()
    assert evaluate(p, base(indication)).decision == 'pass'
    for fact in base(indication):
        for omit in [True, False]:
            facts = base(indication)
            if omit:
                del facts[fact]
            else:
                facts[fact] = None
            r = evaluate(p, facts)
            assert r.decision == 'need_info'
            assert r.missing_facts == [fact]
    for age in [0, 1, 17, 18, 90]:
        assert evaluate(p, dict(base(indication), age_years=age)).decision == 'pass'
    for specialty in SPECIALTIES:
        assert evaluate(p, dict(base(indication), prescriber_specialty=specialty)).decision == 'pass'
    for fact in ['baseline_liver_function_labs_documented', 'no_complete_biliary_obstruction']:
        r = evaluate(p, dict(base(indication), **{fact: False}))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == [fact]


def test_closed_indication_and_gated_facts():
    p = pack()
    for indication in ['other', 'yes', 'no', True, False, 'liver_disease']:
        r = evaluate(p, dict(base(), indication=indication))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == ['indication_fda_labeled']
    assert set(evaluate(p, {}).missing_facts) == {
        'indication', 'prescriber_specialty', 'baseline_liver_function_labs_documented',
        'no_complete_biliary_obstruction'}
    for confirmation in CONFIRMATIONS:
        assert evaluate(p, dict(base(), basd_confirmation=confirmation)).decision == 'pass'
    for confirmation in ['not_met', 'yes', True, False, 'unknown']:
        r = evaluate(p, dict(base(), basd_confirmation=confirmation))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == ['basd_confirmation']
    assert evaluate(p, dict(base(), **{MANIFESTATIONS: False, 'cholbam_used_as_adjunctive_therapy': False})).decision == 'pass'
    assert evaluate(p, dict(base(PD), basd_confirmation='not_met')).decision == 'pass'
    for fact in [MANIFESTATIONS, 'cholbam_used_as_adjunctive_therapy']:
        r = evaluate(p, dict(base(PD), **{fact: False}))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == [fact]


def test_ui_options_and_when():
    p = pack()
    fields = {f['key']: f for f in drug_detail('cholbam')['fact_fields']}
    assert set(fields) == set(base()) | set(base(PD))
    passing = {'indication': {BASD, PD}, 'basd_confirmation': CONFIRMATIONS,
               'prescriber_specialty': SPECIALTIES}
    for fact, field in fields.items():
        assert field['type'] == 'select' and field['free_text'] is False
        indication = PD if fact in [MANIFESTATIONS, 'cholbam_used_as_adjunctive_therapy'] else BASD
        clause = next(c for c in p['criteria'] if c['required_facts'] == [fact])
        if fact in ['basd_confirmation', MANIFESTATIONS, 'cholbam_used_as_adjunctive_therapy']:
            assert clause['when'] == field['when'] == {'fact': 'indication', 'in': [indication]}
        else:
            assert 'when' not in clause and 'when' not in field
        for option in field['options']:
            value = option['value']
            facts = base(value if fact == 'indication' else indication)
            facts[fact] = value
            r = evaluate(p, _coerce_patient(facts))
            expected = 'pass' if value in passing.get(fact, {'yes'}) else 'fail'
            assert r.decision == expected, (fact, value, r)
            if expected == 'fail':
                assert [c['id'] for c in r.failed_clauses] == [clause['id']]
    assert {o['value'] for o in fields['basd_confirmation']['options']} == CONFIRMATIONS | {'not_met'}


def test_metadata_notes_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='Cholbam', generic_name='cholic acid', therapeutic_class='metabolic')
    assert p['source'] == dict(payer='alaska_medicaid', list='Cholbam Criteria',
                              effective_date='2023-03-01',
                              citation='https://health.alaska.gov/media/fwommy3l/202301cholbam_criteria_2023.pdf',
                              criteria_pdf='data/alaska/raw/202301cholbam_criteria_2023.pdf')
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial' and len(p['criteria']) == 7
    assert p['alternatives'] == [] and p['max_units'] is None
    assert 'inferred_required_facts' not in p and 'age_years' not in p['fact_ui']
    notes = ' '.join(p['notes'])
    for term in ['Version 1', '12/19/2022', '01/20/2023', '03/01/2023',
                 'every month for the first 3 months', 'every 3 months for the next 9 months',
                 'every 6 months during the next three years', 'annually thereafter',
                 'lowest dose', 'initial approval 3 months', 'reauthorization 12 months',
                 'improvements in liver function labs', 'Updated labs', '10–15 mg/kg/day',
                 '11–17 mg/kg/day', 'familial hypertriglyceridemia', 'manual review']:
        assert term in notes
    for term in ['AST', 'ALT', 'GGT', 'ALP', 'bilirubin', 'INR']:
        assert term in p['fact_ui']['baseline_liver_function_labs_documented']['label']
    assert (BASE / 'cholbam.json').read_bytes() == (BASE / 'rule_packs/cholbam.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['cholbam'] == p
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 167
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 31
    assert catalog['ofev']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (167, 31)
    assert status['next_candidate'] == 'gralise'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
