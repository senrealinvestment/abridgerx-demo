"""Oral bisphosphonate product routing and three-valued step alternatives."""
import itertools
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _when_applies
from ui.app import _coerce_patient
from ui.loaders import drug_detail

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/bone-resorption-inhibitors.json').read_text())
STEPS = ['alendronate_trial_30_days', 'alendronate_adverse_reaction',
         'alendronate_not_option_medical_necessity']


@pytest.mark.parametrize('product', ['actonel', 'atelvia', 'ibandronate', 'fosamax_plus_d', 'binosto'])
def test_step_truth_table(product):
    for values in itertools.product([True, False, None], repeat=3):
        facts = dict(zip(STEPS, values), product=product)
        facts['effervescent_form_rationale_submitted'] = True
        result = evaluate(PACK, facts)
        expected = 'pass' if True in values else 'need_info' if None in values else 'fail'
        assert result.decision == expected
        assert set(result.missing_facts) == ({k for k,v in zip(STEPS,values) if v is None} if expected == 'need_info' else set())
        for key in STEPS:
            assert evaluate(PACK, dict(product=product, **{key: True}, effervescent_form_rationale_submitted=True)).decision == 'pass'


@pytest.mark.parametrize('strength', [5, 10, 35, 40, 70])
def test_preferred_no_step(strength):
    facts = dict(product='alendronate_sodium', alendronate_strength_mg=strength)
    assert evaluate(PACK, facts).decision == 'pass'
    facts.update({key:False for key in STEPS}, effervescent_form_rationale_submitted=False)
    assert evaluate(PACK, facts).decision == 'pass'
    assert evaluate(PACK, _coerce_patient(dict(product='alendronate_sodium', alendronate_strength_mg=str(strength)))).decision == 'pass'


def test_closed_product_and_strength():
    assert evaluate(PACK, {}).missing_facts == ['product']
    for product in ['other', 'boniva', 'fosamax', True, '']:
        assert evaluate(PACK, {'product':product}).decision == 'fail'
    assert evaluate(PACK, {'product':'alendronate_sodium'}).missing_facts == ['alendronate_strength_mg']
    for strength in [0, 4, 6, 69, 71, 'other']:
        assert evaluate(PACK, dict(product='alendronate_sodium', alendronate_strength_mg=strength)).decision == 'fail'


@pytest.mark.parametrize('step', STEPS)
def test_binosto_rationale_cannot_be_waived(step):
    facts = dict(product='binosto', **{step:True})
    assert evaluate(PACK, facts).missing_facts == ['effervescent_form_rationale_submitted']
    result = evaluate(PACK, dict(facts, effervescent_form_rationale_submitted=False))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['effervescent_form_rationale']
    for product in ['actonel', 'atelvia', 'ibandronate', 'fosamax_plus_d']:
        assert evaluate(PACK, dict(facts, product=product, effervescent_form_rationale_submitted=False)).decision == 'pass'


def test_ui_and_metadata():
    detail = drug_detail('bone-resorption-inhibitors')
    assert detail['can_evaluate']
    fields = {f['key']:f for f in detail['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    for product in ['alendronate_sodium','actonel','binosto']:
        visible = {k for k,f in fields.items() if _when_applies(f.get('when'),{'product':product})}
        expected = {'product','alendronate_strength_mg'} if product == 'alendronate_sodium' else {'product',*STEPS}
        if product == 'binosto':expected.add('effervescent_form_rationale_submitted')
        assert visible == expected
    for key in STEPS:
        assert evaluate(PACK,_coerce_patient({'product':'binosto',key:'yes','effervescent_form_rationale_submitted':'yes'})).decision == 'pass'
    assert PACK['source']['effective_date'] == '2021-03-15'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['alternatives'] == []
    notes = ' '.join(PACK['notes'])
    for text in ['4/19/2013','1 year','30-day supply','manual review']:
        assert text in notes
    assert (BASE/'bone-resorption-inhibitors.json').read_bytes() == (BASE/'rule_packs/bone-resorption-inhibitors.json').read_bytes()
