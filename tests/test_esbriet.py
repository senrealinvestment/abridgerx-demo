"""Esbriet eligibility, indication gating, UI and catalog integration."""
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
IPF = 'idiopathic_pulmonary_fibrosis'
GATED = {'ipf_confirmed_by', 'other_known_causes_of_ild_ruled_out',
         'fvc_percent_predicted_ge_50_within_60_days', 'dlco_percent_predicted_ge_30'}
BOOLS = GATED - {'ipf_confirmed_by'} | {
    'nonsmoker_or_abstinent_ge_6_weeks', 'baseline_liver_function_test_obtained',
    'no_esrd_requiring_dialysis', 'not_combined_with_ofev'}


def pack():
    return json.loads((BASE / 'rule_packs/esbriet.json').read_text())


def base():
    return dict(indication=IPF, age_years=18, ipf_confirmed_by='lung_biopsy',
                prescriber_specialty='pulmonologist', **dict.fromkeys(BOOLS, True))


@pytest.mark.parametrize('confirmation', ['lung_biopsy', 'high_resolution_ct'])
@pytest.mark.parametrize('specialty', ['pulmonologist', 'pulmonologist_consult'])
def test_passing_paths(confirmation, specialty):
    assert evaluate(pack(), dict(base(), ipf_confirmed_by=confirmation,
                                 prescriber_specialty=specialty)).decision == 'pass'


def test_missing_null_and_failures():
    p = pack()
    for fact in base():
        for null in [False, True]:
            facts = base()
            if null:
                facts[fact] = None
            else:
                del facts[fact]
            result = evaluate(p, facts)
            assert result.decision == 'need_info'
            assert result.missing_facts == [fact]
    for fact in BOOLS:
        result = evaluate(p, dict(base(), **{fact: False}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [fact]
    for age, expected in [(17, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')]:
        assert evaluate(p, dict(base(), age_years=age)).decision == expected
    for fact in ['indication', 'ipf_confirmed_by', 'prescriber_specialty']:
        for value in ['other', 'not_met', 'yes', 'no', True, False]:
            assert evaluate(p, dict(base(), **{fact: value})).decision == 'fail'


def test_gating_and_ui():
    p = pack()
    fields = {f['key']: f for f in drug_detail('esbriet')['fact_fields']}
    assert set(fields) == set(base())
    assert set(evaluate(p, {}).missing_facts) == set(base()) - GATED
    for indication in [None, 'other']:
        facts = {k: v for k, v in base().items() if k not in GATED}
        facts['indication'] = indication
        result = evaluate(p, facts)
        assert not (set(result.missing_facts) & GATED)
        assert result.decision == ('need_info' if indication is None else 'fail')
    passing = {'indication': {IPF}, 'age_years': {'18'},
               'ipf_confirmed_by': {'lung_biopsy', 'high_resolution_ct'},
               'prescriber_specialty': {'pulmonologist', 'pulmonologist_consult'}}
    for fact, field in fields.items():
        clause = next(c for c in p['criteria'] if c['required_facts'] == [fact])
        assert field['type'] == 'select' and field['free_text'] is False
        if fact in GATED:
            assert field['when'] == clause['when'] == {'fact': 'indication', 'in': [IPF]}
        else:
            assert 'when' not in field and 'when' not in clause
        for option in field['options']:
            value = option['value']
            result = evaluate(p, _coerce_patient(dict(base(), **{fact: value})))
            assert result.decision == ('pass' if value in passing.get(fact, {'yes'}) else 'fail')
    assert {o['value'] for o in fields['ipf_confirmed_by']['options']} == {'lung_biopsy', 'high_resolution_ct', 'not_met'}


def test_metadata_notes_and_bundles():
    p = pack()
    assert p['drug'] == dict(name='Esbriet', generic_name='pirfenidone', therapeutic_class='pulmonary')
    assert p['source']['effective_date'] == '2021-05-24'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/fn3nn0iv/202104-esbriet_criteria_2021.pdf'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial' and len(p['criteria']) == 11
    assert 'inferred_required_facts' not in p and p['max_units'] is None
    notes = ' '.join(p['notes'])
    for term in ['Version 1', '3/1/21', '4/16/2021', '5/24/2021', 'ALT', 'AST',
                 'bilirubin', 'Gastrointestinal', 'Photosensitivity', '3 months',
                 '12 months', 'improvement and effectiveness', '180 × 267 mg',
                 '90 × 801 mg', '30 days', 'manual review']:
        assert term in notes
    assert (BASE / 'esbriet.json').read_bytes() == (BASE / 'rule_packs/esbriet.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['esbriet'] == p
    assert p['alternatives'] == ['ofev']
    assert catalog['ofev']['alternatives'] == ['esbriet']
    assert catalog['ofev']['encoding_status'] == 'partial'
    assert len(catalog['ofev']['criteria']) == 15
    assert evaluate(catalog['ofev'], base()).decision == 'need_info'
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 133
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 65
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (133, 65)
    assert status['next_candidate'] == 'interleukin-5-inhibitors'
    assert catalog['ofev']['encoding_status'] == 'partial'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
