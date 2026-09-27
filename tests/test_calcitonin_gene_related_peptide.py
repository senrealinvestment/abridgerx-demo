"""Alaska CGRP class: closed indications, branch gates and shared denials."""
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

SLUG = 'calcitonin-gene-related-peptide'
BRANCHES = {
    'migraine_prevention': dict(migraine_days_ge_4_per_month=True,
        failed_two_prophylactic_classes_ge_2mo_each='two_different_classes_ge_2mo_each'),
    'migraine_acute': dict(medication_overuse_ruled_out=True,
        failed_one_prophylactic_ge_2mo='one_prophylactic_ge_2mo',
        failed_two_triptans_or_contraindicated='two_different_triptans_failed',
        not_on_strong_cyp3a4_inhibitor=True),
}


def pack():
    return json.loads((BASE / 'rule_packs' / f'{SLUG}.json').read_text())


def facts(indication):
    return dict(indication=indication, within_fda_labeled_age_for_agent=True,
        prescriber_specialty='neurologist',
        not_concurrent_two_oral_or_two_injectable_cgrp=True,
        not_concurrent_two_cgrp_for_same_prevention_or_acute_indication=True,
        **BRANCHES[indication])


@pytest.mark.parametrize('indication', BRANCHES)
def test_paths_missing_and_every_option(indication):
    p = pack()
    patient = facts(indication)
    assert evaluate(p, patient).decision == 'pass'
    for key in patient:
        missing = patient.copy()
        del missing[key]
        result = evaluate(p, missing)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
        if key == 'indication':
            continue
        for option in p['fact_ui'][key]['options']:
            value = option['value']
            result = evaluate(p, _coerce_patient(dict(patient, **{key: value})))
            fails = value in ['false', 'not_met']
            assert result.decision == ('fail' if fails else 'pass'), (key, value, result)
            if fails:
                assert [c['id'] for c in result.failed_clauses] == [key]
                assert result.citations == [p['source']['citation']]
    stale = {k: False if v is True else 'not_met'
             for ind, fields in BRANCHES.items() if ind != indication for k, v in fields.items()}
    assert evaluate(p, dict(patient, **stale)).decision == 'pass'


@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', True, False, 'other'])
def test_closed_indication(value):
    result = evaluate(pack(), dict(facts('migraine_prevention'), indication=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


def test_ui_gates_metadata_and_notes():
    p = pack()
    fields = {f['key']: f for f in drug_detail(SLUG)['fact_fields']}
    assert set(fields) == {k for ind in BRANCHES for k in facts(ind)}
    assert [o['value'] for o in fields['indication']['options']] == list(BRANCHES)
    gates = {key: {'fact': 'indication', 'in': [ind]} for ind, fs in BRANCHES.items() for key in fs}
    for c in p['criteria']:
        key = c['id']
        assert c.get('when') == p['fact_ui'][key].get('when') == fields[key].get('when') == gates.get(key)
        assert fields[key]['type'] == 'select' and fields[key]['option_source'] == 'fact_ui'
        assert c['citation'] == p['source']['citation']
    assert set(evaluate(p, {}).missing_facts) == set(fields) - set(gates)
    assert 'age_years' not in fields and 'used_for_prophylaxis' not in fields
    assert 'inferred_required_facts' not in p
    assert p['encoding_status'] == 'partial' and p['max_units'] is None and p['alternatives'] == []
    assert p['drug']['therapeutic_class'] == 'cgrp-antagonists'
    assert p['source']['effective_date'] == '2025-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/iwgcf1bi/cgrp_antagonist_inj-oral_criteria_update_2025.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/cgrp_antagonist_inj-oral_criteria_update_2025.pdf'
    for text in ['Version 2', '10/12/2018', '09/18/2020', '09/19/2025', '11/1/2025',
                 '3 months', '12 months', '34 days', 'injection site reactions', 'CYP3A4',
                 'criteria 3 and 5', 'beta blockers', 'manual review']:
        assert text in ' '.join(p['notes'])


def test_catalog_mirrors_and_scope():
    p = pack()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack(SLUG) == (SLUG, p)
    assert (BASE / f'{SLUG}.json').read_bytes() == (BASE / 'rule_packs' / f'{SLUG}.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 73
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 125
    assert catalog['anzupgo']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 73 and status['encoding_text_only'] == 125
    assert status['next_candidate'] == 'strensiq'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
