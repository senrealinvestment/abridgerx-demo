"""Alaska Lupkynis eligibility, explicit denials, UI and catalog integrity."""
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
PACK = json.loads((BASE / 'lupkynis.json').read_text())
BOOLEAN_FACTS = [k for k, v in PACK['fact_ui'].items() if v['options'][0]['value'] == 'yes']


def facts():
    return dict(indication='active_lupus_nephritis', age_years=18,
                prescriber_specialty_ln='nephrologist_or_rheumatologist_or_consult',
                ln_biopsy_class='iii_or_iv', upcr_band='1_5_to_below_2',
                background_therapy='concurrent_both', **dict.fromkeys(BOOLEAN_FACTS, True))


def test_metadata_and_notes():
    assert PACK['drug'] == dict(name='Lupkynis', generic_name='voclosporin', therapeutic_class='calcineurin-inhibitor')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2021-11-01'
    assert PACK['pdl_status'] == 'unknown'
    assert 'inferred_required_facts' not in PACK
    assert PACK['max_units']['quantity'] == 180 and PACK['max_units']['days_supply'] == 30
    notes = ' '.join(PACK['notes'])
    for text in ['two weeks', 'four weeks', '3 months', '6 months', 'stabilization', 'slope of decline', 'nephrotoxicity', 'neurotoxicity', 'electrocardiograms', 'electrolyte', 'live vaccines', 'manual review']:
        assert text in notes


@pytest.mark.parametrize('indication', ['lupus_nephritis', 'systemic_lupus_erythematosus', 'other', 'yes', True, False])
def test_closed_indication(indication):
    r = evaluate(PACK, dict(facts(), indication=indication))
    assert r.decision == 'fail'
    assert [c['id'] for c in r.failed_clauses] == ['indication']


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age(age, decision):
    assert evaluate(PACK, dict(facts(), age_years=age)).decision == decision


@pytest.mark.parametrize('biopsy', ['iii_or_iv', 'iii_or_iv_with_v', 'v_only', 'other_or_unconfirmed'])
@pytest.mark.parametrize('upcr', ['below_1_5', '1_5_to_below_2', 'at_least_2'])
def test_biopsy_and_upcr(biopsy, upcr):
    expected = (biopsy == 'iii_or_iv' and upcr != 'below_1_5') or (biopsy == 'iii_or_iv_with_v' and upcr == 'at_least_2')
    assert evaluate(PACK, dict(facts(), ln_biopsy_class=biopsy, upcr_band=upcr)).decision == ('pass' if expected else 'fail')


@pytest.mark.parametrize('therapy', ['concurrent_both', 'inadequate_efficacy', 'significant_intolerance', 'contraindication', 'none', 'mycophenolate_only', 'steroid_only'])
def test_background_regimen_and_exceptions(therapy):
    assert evaluate(PACK, dict(facts(), background_therapy=therapy)).decision == ('pass' if therapy in ['concurrent_both', 'inadequate_efficacy', 'significant_intolerance', 'contraindication'] else 'fail')


def test_every_lab_and_denial_and_specialty():
    assert evaluate(PACK, facts()).decision == 'pass'
    for key in BOOLEAN_FACTS + ['prescriber_specialty_ln']:
        r = evaluate(PACK, dict(facts(), **{key: False if key in BOOLEAN_FACTS else 'none'}))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == [key]
    assert set(BOOLEAN_FACTS) == {'current_lfts_submitted', 'current_upcr_submitted', 'current_potassium_submitted', 'baseline_egfr_submitted', 'not_pregnant', 'baseline_egfr_above_45', 'baseline_bp_acceptable', 'not_taking_cyclophosphamide', 'no_required_strong_cyp3a4_inhibitor', 'no_severe_hepatic_impairment'}


def test_missing_facts_and_ui_roundtrip():
    fields = {f['key']: f for f in drug_detail('lupkynis')['fact_fields']}
    assert set(fields) == set(facts())
    for key in facts():
        patient = facts(); del patient[key]
        result = evaluate(PACK, patient)
        assert result.decision == 'need_info' and result.missing_facts == [key]
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            patient = {k: 'yes' if v is True else str(v) for k, v in facts().items()}
            patient[key] = option['value']
            result = evaluate(PACK, _coerce_patient(patient))
            assert result.decision in ['pass', 'fail']
    assert evaluate(PACK, _coerce_patient({k: 'yes' if v is True else str(v) for k, v in facts().items()})).decision == 'pass'
    assert set(evaluate(PACK, {}).missing_facts) == set(facts())


def test_catalog_mirrors_and_peers():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 133
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 65
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert catalog['lupkynis']['alternatives'] == ['benlysta']
    assert catalog['benlysta']['alternatives'] == ['lupkynis']
    for slug in ['lupkynis', 'benlysta']:
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / f'rule_packs/{slug}.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (133, 65)
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'interleukin-5-inhibitors'
    assert catalog[status['next_candidate']]['encoding_status'] == 'text_only'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
