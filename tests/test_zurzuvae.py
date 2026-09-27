"""Alaska Zurzuvae source-specific rules, UI and catalog regression checks."""
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


def pack():
    return json.loads((BASE / 'rule_packs/zurzuvae.json').read_text())


def facts(**changes):
    result = {k: True for k in pack()['fact_ui']}
    result.update(indication='postpartum_depression', age_years=18,
                  prior_zulresso_or_zurzuvae_current_pregnancy=False)
    result.update(changes)
    return result


def test_age_and_closed_indication():
    for age in [18, 19, 65]:
        assert evaluate(pack(), facts(age_years=age)).decision == 'pass'
    for age in [0, 17, 17.9]:
        result = evaluate(pack(), facts(age_years=age))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['age_years']
    for indication in ['major_depressive_disorder', 'other', 'yes', True, False]:
        assert evaluate(pack(), facts(indication=indication)).decision == 'fail'


def test_each_clinical_gate_and_denial():
    for key, value in facts().items():
        if isinstance(value, bool):
            result = evaluate(pack(), facts(**{key: not value}))
            assert result.decision == 'fail'
            assert [c['id'] for c in result.failed_clauses] == [key]
    result = evaluate(pack(), facts(egfr_at_least_15=False,
                                   prior_zulresso_or_zurzuvae_current_pregnancy=True))
    assert len(result.failed_clauses) == 2


def test_missing_and_null():
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


def test_ui_and_attestation_semantics():
    detail = drug_detail('zurzuvae')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            patient = _coerce_patient(facts(**{key: option['value']}))
            result = evaluate(pack(), patient)
            assert result.decision == ('pass' if patient[key] == facts()[key] else 'fail')
    labels = {k: v['label'] for k, v in fields.items()}
    for key, terms in {
        'major_depressive_episode_onset_window': ['no earlier than the third trimester', 'no later than 4 weeks'],
        'within_12_months_since_delivery': ['No more than 12 months', '12 months included'],
        'antidepressant_trial_or_all_contraindicated': ['therapeutic dose', 'at least 6 weeks', 'at least one', 'SSRI', 'SNRI', 'bupropion', 'mirtazapine', 'TCA', 'OR', 'ALL five'],
        'current_renal_and_liver_labs_within_60_days': ['BOTH renal and liver', '60 days'],
        'egfr_at_least_15': ['at least 15', '15 included', 'below 15'],
        'prior_zulresso_or_zurzuvae_current_pregnancy': ['Zulresso or Zurzuvae', 'current pregnancy'],
    }.items():
        for term in terms:
            assert term in labels[key]


def test_metadata_notes_and_artifacts():
    p = pack()
    assert p['drug'] == dict(name='Zurzuvae', generic_name='zuranolone', therapeutic_class='neuroactive-steroid')
    assert p['source']['effective_date'] == '2024-03-01'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial'
    assert p['alternatives'] == ['raft'] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 9
    notes = ' '.join(p['notes'])
    for term in ['Version 1', '12/18/2023', '01/19/2024', '03/01/2024',
                 'initial approval 1 month', '14 days', 'no extension', '#28',
                 'one course of treatment per pregnancy', 'CYP3A4', 'CYP4A4',
                 'CNS depression', '12 hours', 'addiction', 'fetal harm', 'manual review']:
        assert term in notes
    assert (BASE / 'zurzuvae.json').read_bytes() == (BASE / 'rule_packs/zurzuvae.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('zurzuvae') == ('zurzuvae', p)
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 130
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 68
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (130, 68)
    assert status['next_candidate'] == 'vykattm-xr'
    assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status'] == 'partial')
    for slug in ['vykattm-xr']:
        assert catalog[slug]['encoding_status'] == 'text_only'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
