"""Vumerity Alaska Medicaid shared MS gates and source limitations."""
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
PACK = json.loads((BASE / 'rule_packs/vumerity.json').read_text())
FORMS = ['clinically_isolated_syndrome', 'relapsing_remitting_ms', 'active_secondary_progressive_ms']
FACTS = dict(indication=FORMS[0], age_years=18,
             prescriber_specialty='neurologist_or_ms_specialist_or_consult',
             baseline_cbc_lft_appropriate='all_done_appropriate',
             liver_labs_documented='all_documented',
             reproductive_contraception_counseling='counseled_during_and_6mo_after_last_dose',
             ms_same_indication_step_one='adequate_trial_failure_one_same_ms_form',
             renal_impairment='none_or_mild', concurrent_dimethyl_fumarate='absent')

@pytest.mark.parametrize('form', FORMS)
def test_shared_gates(form):
    facts = dict(FACTS, indication=form)
    assert evaluate(PACK, facts).decision == 'pass'
    assert evaluate(PACK, dict(facts, reproductive_contraception_counseling='not_of_reproductive_potential')).decision == 'pass'
    for clause in PACK['criteria']:
        key = clause['required_facts'][0]
        for option in PACK['fact_ui'][key]['options']:
            value = option['value']
            pred = clause['predicate']
            allowed = (float(value) >= 18 if key == 'age_years' else
                       value in pred['values'] if pred['op'] == 'in' else value == pred['value'])
            result = evaluate(PACK, _coerce_patient(dict(facts, **{key: value})))
            assert result.decision == ('pass' if allowed else 'fail')
            assert [c['id'] for c in result.failed_clauses] == ([] if allowed else [clause['id']])
            assert result.citations
    for age in [0, 17, 17.99]:
        assert evaluate(PACK, dict(facts, age_years=age)).decision == 'fail'

@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert key in result.missing_facts

@pytest.mark.parametrize('value', ['primary_progressive_ms', 'secondary_progressive_ms', 'multiple_sclerosis', 'other', 'yes', 'no', 'unknown', True, False])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication_fda_labeled']

def test_ui_metadata_notes():
    detail = drug_detail('vumerity')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(FACTS)
    assert all(f['type'] == 'select' for f in detail['fact_fields'])
    assert all('when' not in c for c in PACK['criteria'])
    assert all('when' not in ui for ui in PACK['fact_ui'].values())
    assert len(PACK['criteria']) == 9
    assert PACK['drug'] == dict(name='Vumerity', generic_name='diroximel_fumarate', therapeutic_class='fumarate')
    assert PACK['source']['effective_date'] == '2020-03-16'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    for text in ['anaphylaxis', 'angioedema', 'PML', 'lymphocyte', 'liver injury', 'alcohol', 'high-fat, high-calorie', '30 days', '12 months', '120 × 231mg', 'manual review']:
        assert text in ' '.join(PACK['notes'])

def test_catalog_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['vumerity'] == PACK
    assert (BASE / 'vumerity.json').read_bytes() == (BASE / 'rule_packs/vumerity.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 121
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 77
    assert catalog['sunosi']['encoding_status'] == 'text_only'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (121, 77)
    assert status['next_candidate'] == 'sunosi'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
