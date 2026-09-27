"""Archived AK SMA Version 1: product gating and shared eligibility."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _when_applies
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
LAB = 'spinraza_platelet_coag_urine_protein_monitoring'
MOTORS = ['infant_lt_1mo_prescriber_agrees_assess_at_1mo', 'hine_2', 'hfmse',
          'bsid_iii_item_22', 'chop_intend', 'rulm', 'mfm_32']


def pack():
    return json.loads((BASE / 'rule_packs/spinal-muscular-atrophy.json').read_text())


def facts(product='evrysdi'):
    p = dict(product=product, indication='spinal_muscular_atrophy',
             prescriber_specialty='neurologist_specializing_in_sma_or_consult',
             smn1_mutation='homozygous_deletion_or_mutation_smn1',
             baseline_motor_assessment='hine_2',
             contraception_counseling='not_applicable_male_or_not_of_reproductive_potential',
             not_concomitant_evrysdi_and_spinraza='not_combined',
             no_prior_sma_gene_replacement_therapy='no_prior_gene_therapy')
    p.update({'age_years': 2/12} if product == 'evrysdi' else {LAB: 'will_perform_baseline_and_prior_each_dose'})
    return p


@pytest.mark.parametrize('product', ['evrysdi', 'spinraza'])
def test_options_missing_and_ui(product):
    p = pack()
    fields = {f['key']: f for f in drug_detail('spinal-muscular-atrophy')['fact_fields']}
    patient = facts(product)
    visible = {k for k, f in fields.items() if _when_applies(f.get('when'), patient)}
    assert visible == set(patient)
    for c in p['criteria']:
        if 'when' in c:
            key = 'age_years' if c['id'] == 'age_fda_labeled' else c['id']
            assert c['when'] == fields[key]['when']
    for key in visible:
        f = fields[key]
        assert f['type'] == 'select' and not f['free_text']
        for option in f['options']:
            value = option['value']
            if key == 'product':
                continue
            accepted = {str(patient[key])}
            if key == 'smn1_mutation': accepted.add('compound_heterozygous_mutation_smn1')
            if key == 'baseline_motor_assessment': accepted.update(MOTORS)
            if key == 'contraception_counseling': accepted.add('female_reproductive_potential_advised_contraception_during_and_1mo_after')
            result = evaluate(p, _coerce_patient(dict(patient, **{key: value})))
            assert result.decision == ('pass' if value in accepted else 'fail'), (key, value)
            if result.decision == 'fail':
                assert result.citations
        for missing in [None, 'omit']:
            trial = dict(patient)
            if missing is None: trial[key] = None
            else: del trial[key]
            result = evaluate(p, trial)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]


def test_product_gates_and_age_boundary():
    p = pack()
    for age in [0, 1/12, 2/12 - .000001, 2/12, 1, 80]:
        result = evaluate(p, dict(facts(), age_years=age))
        assert result.decision == ('pass' if age >= 2/12 else 'fail')
        assert evaluate(p, dict(facts('spinraza'), age_years=age)).decision == 'pass'
    assert evaluate(p, dict(facts(), **{LAB: 'will_not'})).decision == 'pass'
    assert evaluate(p, facts('spinraza')).decision == 'pass'
    switched = dict(facts(), product='spinraza')
    assert evaluate(p, switched).missing_facts == [LAB]
    switched = dict(facts('spinraza'), product='evrysdi')
    assert evaluate(p, switched).missing_facts == ['age_years']
    empty = evaluate(p, {})
    assert 'product' in empty.missing_facts
    assert LAB not in empty.missing_facts and 'age_years' not in empty.missing_facts


@pytest.mark.parametrize('key', ['product', 'indication'])
@pytest.mark.parametrize('value', ['zolgensma', 'other', 'yes', 'unknown', True, False])
def test_closed_lists(key, value):
    assert evaluate(pack(), dict(facts(), **{key: value})).decision == 'fail'


def test_metadata_catalog_and_notes():
    p = pack()
    assert p['encoding_status'] == 'partial' and p['source']['effective_date'] == '2022-11-01'
    assert 'inferred_required_facts' not in p
    assert p['drug']['generic_name'] == 'risdiplam / nusinersen'
    assert p['alternatives'] == ['zolgensma']
    notes = ' '.join(p['notes'])
    for text in ['Version: 1', '2/15/2022', '9/16/2022', '11/1/2022', '6 months',
                 '12 months', 'stability', '0.2 mg/kg', '0.25 mg/kg', '5 mg',
                 '12 mg', '14-day', '30 days', '4 months', 'J2326', 'manual review']:
        assert text in notes
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 160
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 38
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    for slug in ['spinal-muscular-atrophy', 'zolgensma']:
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / 'rule_packs' / f'{slug}.json').read_bytes()
    assert catalog['zolgensma']['alternatives'] == ['spinal-muscular-atrophy']
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (160, 38)
    assert status['next_candidate'] == 'viberzi'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for ext in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()
