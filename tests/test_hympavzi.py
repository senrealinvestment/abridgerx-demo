"""Alaska Hympavzi: closed prophylaxis indications and shared eligibility gates."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/alaska/parsed'
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog

INDS = ['hemophilia_a_without_fviii_inhibitors_prophylaxis',
        'hemophilia_b_without_fix_ix_inhibitors_prophylaxis']
SEVERITIES = ['severe_factor_activity_lt_1_percent',
              'ge_2_spontaneous_joint_bleeds_documented']


def pack():
    return json.loads((BASE / 'rule_packs/hympavzi.json').read_text())


def facts(indication=INDS[0]):
    return dict(indication=indication, age_years=12,
                prescriber_specialty='hematologist_or_consult',
                not_combined_with_prophylactic_factor_replacement=True,
                hemophilia_severity_or_joint_bleeds=SEVERITIES[0],
                not_for_breakthrough_bleeding=True,
                new_start_maintenance_dose_le_150mg_weekly='le_150mg_weekly_or_not_new_start')


def test_metadata_and_notes():
    p = pack()
    assert p['drug'] == dict(name='Hympavzi', generic_name='marstacimab-hncq', therapeutic_class='hemophilia')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2025-03-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/vbbktmui/hympavzi_criteria_2025.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/hympavzi_criteria_2025.pdf'
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 7
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    for text in ['Version: 1', '11/12/2024', '01/17/2025', '03/1/2025',
                 '3 months', '12 months', '8 prefilled 150mg/ml', '28 days',
                 'thromboembolic', 'interrupt', 'fetal harm', 'manual review']:
        assert text in ' '.join(p['notes'])


@pytest.mark.parametrize('indication', INDS)
@pytest.mark.parametrize('severity', SEVERITIES)
@pytest.mark.parametrize('age', [12, 18, 80])
def test_approval_paths(indication, severity, age):
    assert evaluate(pack(), dict(facts(indication), age_years=age,
                    hemophilia_severity_or_joint_bleeds=severity)).decision == 'pass'


@pytest.mark.parametrize('indication', INDS)
def test_each_denial_and_age_boundary(indication):
    for fact, value in dict(age_years=11.99, prescriber_specialty='none',
            not_combined_with_prophylactic_factor_replacement=False,
            hemophilia_severity_or_joint_bleeds='not_met',
            not_for_breakthrough_bleeding=False,
            new_start_maintenance_dose_le_150mg_weekly='above_150mg_weekly_new_start').items():
        result = evaluate(pack(), dict(facts(indication), **{fact: value}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [fact]
        assert result.citations == [pack()['source']['citation']]


@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', True, False, 'other',
    'hemophilia_a_with_fviii_inhibitors_prophylaxis', 'hemophilia_b_with_fix_inhibitors_prophylaxis',
    'hemophilia_a_prophylaxis', 'breakthrough_bleeding'])
def test_closed_indication(value):
    result = evaluate(pack(), {'indication': value})
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']
    assert not result.missing_facts


@pytest.mark.parametrize('indication', INDS)
def test_missing_facts(indication):
    p = pack()
    assert evaluate(p, {}).missing_facts == ['indication']
    for fact in facts():
        patient = facts(indication)
        del patient[fact]
        result = evaluate(p, patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [fact]


def test_ui_gates_and_round_trip():
    p = pack()
    detail = drug_detail('hympavzi')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == INDS
    assert p['criteria'][0]['predicate'] == dict(op='in', fact='indication', values=INDS)
    for c in p['criteria'][1:]:
        assert c['when'] == fields[c['id']]['when'] == dict(fact='indication', **{'in': INDS})
    for indication in INDS:
        for fact, field in fields.items():
            assert field['type'] == 'select'
            assert field['option_source'] == ('age_bands' if fact == 'age_years' else 'fact_ui')
            for option in field['options']:
                value = option['value']
                result = evaluate(p, _coerce_patient(dict(facts(indication), **{fact: value})))
                negative = value in ['0', 'none', 'false', 'not_met', 'above_150mg_weekly_new_start']
                assert result.decision == ('fail' if negative else 'pass')


def test_catalog_mirrors_and_scope():
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('hympavzi') == ('hympavzi', pack())
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'hympavzi.json').read_bytes() == (BASE / 'rule_packs/hympavzi.json').read_bytes()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 150
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 48
    assert catalog['calcitonin-gene-related-peptide']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 150 and status['encoding_text_only'] == 48
    assert status['next_candidate'] == 'leuprolide'
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
