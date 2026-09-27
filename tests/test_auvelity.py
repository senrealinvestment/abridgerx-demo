"""Auvelity source-specific approval, denial, UI and artifact regression checks."""
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
STEP = 'failed_two_antidepressants_60_days_therapeutic_doses'
DENIALS = ['seizure_disorder', 'current_or_prior_anorexia_or_bulimia',
           'auvelity_within_14_days_of_maoi', 'severe_hepatic_impairment',
           'severe_renal_impairment']


def pack():
    return json.loads((BASE / 'rule_packs/auvelity.json').read_text())


def facts(**changes):
    return dict(dict(indication='major_depressive_disorder', age_years=18,
                     **{STEP: True}, **dict.fromkeys(DENIALS, False)), **changes)


def test_approval_boundaries_and_closed_indication():
    for age in [18, 19, 65]:
        assert evaluate(pack(), facts(age_years=age)).decision == 'pass'
    for age in [0, 17, 17.9]:
        result = evaluate(pack(), facts(age_years=age))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['minimum_age']
    for indication in ['other', 'bipolar_depression', 'yes', 'no', True, False]:
        result = evaluate(pack(), facts(indication=indication))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['indication_fda_labeled']
    result = evaluate(pack(), facts(**{STEP: False}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [STEP]
    label = pack()['fact_ui'][STEP]['label']
    for text in ['two different antidepressants', 'each', 'at least 60 days', 'therapeutic dose']:
        assert text in label


def test_every_denial_independently_and_combined():
    for key in DENIALS:
        result = evaluate(pack(), facts(**{key: True}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['no_' + key]
    result = evaluate(pack(), facts(**dict.fromkeys(DENIALS, True)))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'no_' + k for k in DENIALS}
    assert 'current or prior' in pack()['fact_ui'][DENIALS[1]]['label']
    assert 'within 14 days' in pack()['fact_ui'][DENIALS[2]]['label']


def test_missing_and_null_facts():
    for key in facts():
        for omit in [True, False]:
            patient = facts()
            if omit:
                del patient[key]
            else:
                patient[key] = None
            result = evaluate(pack(), patient)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
    assert set(evaluate(pack(), {}).missing_facts) == set(facts())


def test_ui_options_and_coercion():
    detail = drug_detail('auvelity')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    ids = {c['required_facts'][0]: c['id'] for c in pack()['criteria']}
    passing = dict(indication='major_depressive_disorder', age_years='18',
                   **{STEP: 'yes'}, **dict.fromkeys(DENIALS, 'no'))
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        assert field['options'] == pack()['fact_ui'][key]['options']
        for option in field['options']:
            result = evaluate(pack(), _coerce_patient(facts(**{key: option['value']})))
            assert result.decision == ('pass' if option['value'] == passing[key] else 'fail')
            if result.decision == 'fail':
                assert [c['id'] for c in result.failed_clauses] == [ids[key]]


def test_metadata_notes_and_artifacts():
    p = pack()
    assert p['drug'] == dict(name='Auvelity', generic_name='dextromethorphan hbr / bupropion hcl',
                             therapeutic_class='antidepressants')
    assert p['source'] == dict(payer='alaska_medicaid', list='Auvelity Criteria',
                              effective_date='2025-03-01',
                              citation='https://health.alaska.gov/media/0jpjvndu/auvelity_criteria_2025.pdf',
                              criteria_pdf='data/alaska/raw/auvelity_criteria_2025.pdf')
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial'
    assert p['alternatives'] == [] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 8
    notes = ' '.join(p['notes'])
    for text in ['Version 1', '12/3/2024', '01/17/2025', '03/1/2025',
                 'initial approval 3 months', 'renewal up to 12 months',
                 '68 tablets within 34 days', '2 tablets per day', 'fetal harm',
                 'hypertension', 'boxed warning', 'suicidal thoughts and behaviors', 'manual review']:
        assert text in notes
    assert (BASE / 'auvelity.json').read_bytes() == (BASE / 'rule_packs/auvelity.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('auvelity') == ('auvelity', p)
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 172
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 26
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (172, 26)
    assert status['next_candidate'] == 'long-acting-opioid-analgesics'
    assert catalog[status['next_candidate']]['encoding_status'] == 'text_only'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
