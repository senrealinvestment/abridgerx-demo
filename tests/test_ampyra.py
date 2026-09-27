"""Ampyra Alaska Medicaid Version 2 predicates, UI and artifact regressions."""
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
INDICATION = 'multiple_sclerosis_improve_walking'
RENAL = 'creatinine_clearance_gt_50'
WALK = 'walking_disability_status'
PATHS = ['edss_gt_4_and_lt_7',
         'difficulty_walking_able_25_feet_with_or_without_assistive_device']


def pack():
    return json.loads((BASE / 'rule_packs/ampyra.json').read_text())


def facts(**changes):
    return dict({'indication': INDICATION, RENAL: 'gt_50_ml_min', WALK: PATHS[0]}, **changes)


def test_both_walking_paths_and_renal_denial():
    for path in PATHS:
        assert evaluate(pack(), facts(**{WALK: path})).decision == 'pass'
        result = evaluate(pack(), facts(**{WALK: path, RENAL: 'lte_50_or_not_documented'}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [RENAL]
    result = evaluate(pack(), facts(**{WALK: 'not_met'}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [WALK]


def test_closed_choices():
    for key in facts():
        for invalid in ['yes', 'no', 'unknown', True, False, 'other', 'multiple_sclerosis']:
            result = evaluate(pack(), facts(**{key: invalid}))
            assert result.decision == 'fail'
            assert [c['id'] for c in result.failed_clauses] == [
                'indication_fda_labeled' if key == 'indication' else key]


def test_missing_facts():
    for key in facts():
        patient = facts()
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
    result = evaluate(pack(), {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(facts())


def test_ui_closed_selects_and_coercion():
    detail = drug_detail('ampyra')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    expected = {'indication': [INDICATION], RENAL: ['gt_50_ml_min', 'lte_50_or_not_documented'],
                WALK: PATHS + ['not_met']}
    for key, field in fields.items():
        assert field['type'] == 'select'
        assert not field.get('free_text')
        assert field['options'] == pack()['fact_ui'][key]['options']
        assert [o['value'] for o in field['options']] == expected[key]
    for path in PATHS:
        assert evaluate(pack(), _coerce_patient(facts(**{WALK: path}))).decision == 'pass'
    for key, value in [(RENAL, 'lte_50_or_not_documented'), (WALK, 'not_met')]:
        assert evaluate(pack(), _coerce_patient(facts(**{key: value}))).decision == 'fail'


def test_metadata_and_notes_only_limits():
    p = pack()
    assert p['drug'] == {'name': 'Ampyra', 'generic_name': 'dalfampridine', 'therapeutic_class': 'other'}
    assert p['source']['effective_date'] == '2010-11-19'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/0p0gytxf/ampyra.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/ampyra.pdf'
    assert p['encoding_status'] == 'partial'
    assert p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 3
    assert {c['predicate']['fact'] for c in p['criteria']} == set(facts())
    assert p['criteria'][1]['predicate'] == {'op': 'eq', 'fact': RENAL, 'value': 'gt_50_ml_min'}
    assert p['criteria'][2]['predicate'] == {'op': 'in', 'fact': WALK, 'values': PATHS}
    assert p['max_units'] is None
    notes = ' '.join(p['notes'])
    for text in ['Version 2', '10/14/2010', '11/19/2010', '09/19/2014', 'up to 6 months',
                 'AND', 'increase in walking speed', '30-day supply', '2 tablets/day',
                 'manual review', 'approval criterion 3 OR']:
        assert text in notes


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('ampyra') == ('ampyra', pack())
    assert (BASE / 'ampyra.json').read_bytes() == (BASE / 'rule_packs/ampyra.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 178
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 20
    assert catalog['anzupgo']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (178, 20)
    assert status['next_candidate'] == 'oral-buprenorphine-based-medication-assisted-therapy-office-based-opioid-treatme'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
