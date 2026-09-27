"""Qutenza: closed indications and every required prior-therapy category."""
import gzip
import itertools
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.loaders import drug_detail, load_rule_pack_catalog
from ui.app import _coerce_patient

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/qutenza.json').read_text())
INDICATIONS = ['neuropathic_pain_postherpetic_neuralgia', 'neuropathic_pain_dpn_of_the_feet']
TRIALS = ['gabapentin_or_pregabalin_trial', 'tca_trial', 'topical_diclofenac_trial', 'lidocaine_patch_5_percent_trial']
FAILURE = 'failed_at_least_4_weeks_therapeutic_dose'


def facts_for(indication):
    return dict(age_years=18, indication=indication, hcp_only_application='confirmed',
                **{key: FAILURE for key in TRIALS})


@pytest.mark.parametrize('indication', INDICATIONS)
def test_all_four_categories_and_exceptions(indication):
    facts = facts_for(indication)
    for choices in itertools.product([FAILURE, 'contraindicated'], repeat=4):
        assert evaluate(PACK, dict(facts, **dict(zip(TRIALS, choices)))).decision == 'pass'
    for key in facts:
        missing = dict(facts)
        del missing[key]
        for patient in [missing, dict(facts, **{key: None})]:
            result = evaluate(PACK, patient)
            assert result.decision == 'need_info'
            assert key in result.missing_facts
    for key in TRIALS:
        for value in ['not_met', 'intolerant', 'failed', 'failed_3_weeks',
                      'failed_4_weeks_subtherapeutic_dose', True, False, 'unknown']:
            result = evaluate(PACK, dict(facts, **{key: value}))
            assert result.decision == 'fail'
            assert key in [c['id'] for c in result.failed_clauses]
            assert PACK['source']['citation'] in result.citations


@pytest.mark.parametrize('age,decision', [(17, 'fail'), (17.99, 'fail'), (18, 'pass'), (90, 'pass')])
def test_age(age, decision):
    assert evaluate(PACK, dict(facts_for(INDICATIONS[0]), age_years=age)).decision == decision


def test_closed_indications_and_professional_application():
    facts = facts_for(INDICATIONS[0])
    for value in ['other', 'neuropathic_pain', 'dpn', 'postherpetic_neuralgia', True, False]:
        assert evaluate(PACK, dict(facts, indication=value)).decision == 'fail'
    for value in ['not_met', 'self_administration', True, False]:
        assert evaluate(PACK, dict(facts, hcp_only_application=value)).decision == 'fail'
    assert evaluate(PACK, _coerce_patient(dict(facts, age_years='18'))).decision == 'pass'
    assert evaluate(PACK, {}).decision == 'need_info'


def test_metadata_ui_notes_and_catalog():
    fields = {f['key']: f for f in drug_detail('qutenza')['fact_fields']}
    assert set(fields) == set(facts_for(INDICATIONS[0]))
    assert len(PACK['criteria']) == 7
    assert PACK['drug']['generic_name'] == 'capsaicin'
    assert PACK['drug']['therapeutic_class'] == 'trpv1-agonist'
    assert PACK['source']['effective_date'] == '2024-03-01'
    assert PACK['encoding_status'] == 'partial' and PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    notes = ' '.join(PACK['notes'])
    for phrase in ['eyes', 'mucous membranes', 'blood pressure', 'burning and pain', 'sensory function',
                   '1 month', '12 months', '4 patches', '90 days', 'manual review']:
        assert phrase in notes
    catalog = load_rule_pack_catalog()
    assert catalog['qutenza'] == PACK
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 152
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 46
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    assert (BASE / 'qutenza.json').read_bytes() == (BASE / 'rule_packs/qutenza.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (152, 46)
    assert status['next_candidate'] == 'marinol'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
