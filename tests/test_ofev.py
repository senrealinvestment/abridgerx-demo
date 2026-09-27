"""Ofev's three indication branches, threshold attestations and catalog integration."""
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
SSC = 'ssc_associated_ild'
CF = 'chronic_fibrosing_ild_progressive_phenotype'
SHARED = {'nonsmoker_or_abstinent_ge_6_weeks', 'baseline_liver_function_test_obtained',
          'no_moderate_to_severe_hepatic_impairment', 'not_combined_with_esbriet'}
FVC40 = 'fvc_percent_predicted_ge_40_within_60_days'
BRANCHES = {
    IPF: {'ipf_confirmed_by', 'other_known_causes_of_ild_ruled_out', FVC40, 'dlco_percent_predicted_ge_30'},
    SSC: {'ssc_ild_confirmed_by_hrct', FVC40},
    CF: {'chronic_fibrosing_ild_progressive_phenotype_diagnosed',
         'fvc_percent_predicted_ge_45_within_60_days', 'dlco_percent_predicted_30_to_79'},
}
GATED = set.union(*BRANCHES.values())


def pack():
    return json.loads((BASE / 'rule_packs/ofev.json').read_text())


def patient(indication):
    facts = dict(indication=indication, age_years=18, prescriber_specialty='pulmonologist',
                 **dict.fromkeys(SHARED | BRANCHES[indication], True))
    if indication == IPF:
        facts['ipf_confirmed_by'] = 'lung_biopsy'
    return facts


@pytest.mark.parametrize('indication', BRANCHES)
@pytest.mark.parametrize('specialty', ['pulmonologist', 'pulmonologist_consult'])
def test_passing_and_irrelevant_failures(indication, specialty):
    facts = dict(patient(indication), prescriber_specialty=specialty)
    assert evaluate(pack(), facts).decision == 'pass'
    facts.update(dict.fromkeys(GATED - BRANCHES[indication], False))
    assert evaluate(pack(), facts).decision == 'pass'
    if indication == IPF:
        facts['ipf_confirmed_by'] = 'high_resolution_ct'
        assert evaluate(pack(), facts).decision == 'pass'


@pytest.mark.parametrize('indication', BRANCHES)
def test_missing_null_and_failed_requirements(indication):
    for fact in patient(indication):
        for null in [False, True]:
            facts = patient(indication)
            if null:
                facts[fact] = None
            else:
                del facts[fact]
            result = evaluate(pack(), facts)
            assert result.decision == 'need_info'
            assert result.missing_facts == [fact]
    for fact in SHARED | BRANCHES[indication] - {'ipf_confirmed_by'}:
        result = evaluate(pack(), dict(patient(indication), **{fact: False}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [fact]
    for age, expected in [(17, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')]:
        assert evaluate(pack(), dict(patient(indication), age_years=age)).decision == expected
    for fact in ['indication', 'prescriber_specialty'] + (['ipf_confirmed_by'] if indication == IPF else []):
        for value in ['other', 'not_met', 'yes', 'no', True, False]:
            assert evaluate(pack(), dict(patient(indication), **{fact: value})).decision == 'fail'


def test_closed_indication_and_gating():
    p = pack()
    assert set(p['criteria'][0]['predicate']['values']) == set(BRANCHES)
    for indication, expected in [(None, 'need_info'), ('other', 'fail')]:
        facts = dict(patient(IPF), indication=indication)
        for key in GATED:
            facts.pop(key, None)
        result = evaluate(p, facts)
        assert result.decision == expected
        assert not set(result.missing_facts) & GATED
    assert set(evaluate(p, {}).missing_facts) == SHARED | {'indication', 'age_years', 'prescriber_specialty'}


def test_ui_options_and_exact_branch_gates():
    p = pack()
    fields = {f['key']: f for f in drug_detail('ofev')['fact_fields']}
    assert set(fields) == GATED | SHARED | {'indication', 'age_years', 'prescriber_specialty'}
    for fact, field in fields.items():
        clause = next(c for c in p['criteria'] if c['required_facts'] == [fact])
        assert field['type'] == 'select' and field['free_text'] is False
        if fact in GATED:
            assert field['when'] == clause['when']
            assert set(clause['when']['in']) == {i for i in BRANCHES if fact in BRANCHES[i]}
        else:
            assert 'when' not in clause and 'when' not in field
        if fact == 'indication':
            assert {o['value'] for o in field['options']} == set(BRANCHES)
            continue
        for indication in BRANCHES:
            if fact in GATED and fact not in BRANCHES[indication]:
                continue
            passing = {'age_years': {'18'}, 'prescriber_specialty': {'pulmonologist', 'pulmonologist_consult'},
                       'ipf_confirmed_by': {'lung_biopsy', 'high_resolution_ct'}}
            for option in field['options']:
                value = option['value']
                result = evaluate(p, _coerce_patient(dict(patient(indication), **{fact: value})))
                assert result.decision == ('pass' if value in passing.get(fact, {'yes'}) else 'fail')
    assert {o['value'] for o in fields['ipf_confirmed_by']['options']} == {'lung_biopsy', 'high_resolution_ct', 'not_met'}
    for fact, terms in [(FVC40, ['≥40%', '60 days']), ('fvc_percent_predicted_ge_45_within_60_days', ['≥45%', '60 days']),
                        ('dlco_percent_predicted_30_to_79', ['30–79%'])]:
        assert all(term in fields[fact]['label'] for term in terms)
    assert 'fvc_percent_predicted_ge_50_within_60_days' not in fields


def test_metadata_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='Ofev', generic_name='nintedanib', therapeutic_class='respiratory')
    assert p['source']['effective_date'] == '2021-03-15'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/4ybbe3te/202101-ofev_criteria_2021.pdf'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial' and len(p['criteria']) == 15
    assert 'inferred_required_facts' not in p and p['max_units'] is None
    notes = ' '.join(p['notes'])
    for term in ['Version 1', '12/02/20', '1/15/21', '3/15/21', 'ALT', 'AST', 'bilirubin',
                 'perforation', 'diarrhea', 'fetal harm', 'contraception', 'bleeding',
                 '3 months', '12 months', '60 × 100 mg', '60 × 150 mg', '30 days', 'manual review']:
        assert term in notes
    assert (BASE / 'ofev.json').read_bytes() == (BASE / 'rule_packs/ofev.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['ofev'] == p and p['alternatives'] == ['esbriet']
    assert catalog['esbriet']['alternatives'] == ['ofev']
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 82
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 116
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (82, 116)
    assert status['next_candidate'] == 'yorvipath'
    assert catalog[status['next_candidate']]['encoding_status'] == 'text_only'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
