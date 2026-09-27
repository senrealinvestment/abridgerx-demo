"""Xyrem/Xywav shared narcolepsy gates and product-specific exclusions."""
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
PACK = json.loads((BASE / 'rule_packs/xyrem.json').read_text())
FACTS = dict(product='xyrem', indication='excessive_daytime_sleepiness_in_narcolepsy',
             age_years=7, diagnosis_letter_medical_necessity='documented_with_letter',
             patient_rems_enrollment='enrolled', provider_rems_enrollment='enrolled',
             prescriber_specialty='sleep_specialist', concomitant_cns_depressants='absent',
             prior_use_drug_screen='verified_absent_prior_to_use',
             major_depressive_disorder_evaluation='evaluated',
             substance_misuse_history_evaluation='evaluated',
             cns_stimulant_step='failed_ge_1_after_ge_30_days',
             wakefulness_promoting_step='failed_ge_1_after_ge_30_days',
             sleep_logs_last_30_days='submitted_last_30_days', heart_failure='absent',
             uncontrolled_hypertension='absent', impaired_renal_function='absent',
             succinic_semialdehyde_dehydrogenase_deficiency='absent',
             sedative_hypnotic_agents='absent', alcohol_use='absent')
XYREM_ONLY = ['heart_failure', 'uncontrolled_hypertension', 'impaired_renal_function']

@pytest.mark.parametrize('product', ['xyrem', 'xywav'])
@pytest.mark.parametrize('indication', ['excessive_daytime_sleepiness_in_narcolepsy', 'cataplexy_in_narcolepsy'])
def test_paths(product, indication):
    facts = dict(FACTS, product=product, indication=indication)
    assert evaluate(PACK, facts).decision == 'pass'
    for key in FACTS:
        if key == 'age_years' or (product == 'xywav' and key in XYREM_ONLY):
            continue
        clause = next(c for c in PACK['criteria'] if c['id'] == key)
        for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['other', 'yes', 'no', True, False]:
            result = evaluate(PACK, dict(facts, **{key: value}))
            allowed = value in clause['predicate']['values']
            assert result.decision == ('pass' if allowed else 'fail')
            assert [c['id'] for c in result.failed_clauses] == ([] if allowed else [key])
            assert result.citations

@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]

@pytest.mark.parametrize('key', XYREM_ONLY)
@pytest.mark.parametrize('value', [None, 'present', 'other'])
def test_xywav_skips_xyrem_denials(key, value):
    assert evaluate(PACK, dict(FACTS, product='xywav', **{key: value})).decision == 'pass'
    facts = dict(FACTS, product='xywav')
    for field in XYREM_ONLY:
        del facts[field]
    assert evaluate(PACK, facts).decision == 'pass'

@pytest.mark.parametrize('age,decision', [(0,'fail'), (6,'fail'), (6.99,'fail'), (7,'pass'), (80,'pass')])
def test_age(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision

@pytest.mark.parametrize('stimulant', ['failed_ge_1_after_ge_30_days', 'contraindicated'])
@pytest.mark.parametrize('wakefulness', ['failed_ge_1_after_ge_30_days', 'contraindicated'])
def test_independent_steps(stimulant, wakefulness):
    facts = dict(FACTS, cns_stimulant_step=stimulant, wakefulness_promoting_step=wakefulness)
    assert evaluate(PACK, facts).decision == 'pass'
    for key in ['cns_stimulant_step', 'wakefulness_promoting_step']:
        for value in ['trial_under_30_days', 'not_failed']:
            assert evaluate(PACK, dict(facts, **{key: value})).decision == 'fail'

def test_ui_metadata_notes():
    detail = drug_detail('xyrem')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    for key in XYREM_ONLY:
        assert PACK['fact_ui'][key]['when'] == {'fact':'product', 'eq':'xyrem'}
    assert evaluate(PACK, _coerce_patient(dict(FACTS, age_years='7'))).decision == 'pass'
    assert PACK['source']['effective_date'] == '2021-01-11'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    for text in ['sodium_oxybate', 'oxybate', 'depression', 'suicidality', 'motor', 'cognitive', 'high sodium', 'sleepwalking', '3 months', '6 months', 'responding positively', '9 g/day', '9 mg/day', '3 × 180ml', 'manual review']:
        assert text in ' '.join(PACK['notes'])

def test_catalog_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['xyrem'] == PACK
    assert 'xywav' not in catalog
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 163
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 35
    assert (BASE/'xyrem.json').read_bytes() == (BASE/'rule_packs/xyrem.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    status = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (163,35)
    assert status['next_candidate'] == 'vecamyl'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json','ENCODING_STATUS.md']:
        assert (BASE/name).read_bytes() == (BASE.parent/name).read_bytes()
