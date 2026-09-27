"""Isturisa eligibility attestations, safety exclusions and catalog integrity."""
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
PACK = json.loads((BASE / 'rule_packs/isturisa.json').read_text())
FACTS = dict(
    indication='cushings_disease', age_years=18,
    prescriber_specialty='diagnosis_specialist_or_consult',
    surgery_not_option_or_not_curative=True,
    two_prior_therapies_ge_30_days=True,
    urine_free_cortisol_obtained=True,
    baseline_ecg_and_periodic_monitoring=True,
    baseline_potassium_magnesium_corrected_and_monitoring=True,
    not_currently_lactating=True,
    no_adrenal_insufficiency_symptoms=True,
)

def test_eligible():
    assert evaluate(PACK, FACTS).decision == 'pass'


@pytest.mark.parametrize('fact', FACTS)
def test_missing_fact(fact):
    patient = FACTS.copy()
    del patient[fact]
    result = evaluate(PACK, patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [fact]


@pytest.mark.parametrize('value', ['yes', 'no', 'unknown', 'other', True, False, 'cushings_syndrome', 'ectopic_acth_syndrome'])
def test_closed_indication(value):
    result = evaluate(PACK, dict(FACTS, indication=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication']


@pytest.mark.parametrize('age,decision', [(0, 'fail'), (17, 'fail'), (17.99, 'fail'), (18, 'pass'), (80, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(PACK, dict(FACTS, age_years=age)).decision == decision


def test_ui_options_and_all_denials():
    fields = {f['key']: f for f in drug_detail('isturisa')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert fields['indication']['options'] == [{'value': 'cushings_disease', 'label': "Persistent or recurring Cushing's disease"}]
    assert all('when' not in c for c in PACK['criteria'])
    denied = {'no', '0', 'none'}
    for fact, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(PACK, _coerce_patient(dict(FACTS, **{fact: value})))
            assert result.decision == ('fail' if value in denied else 'pass'), (fact, value)
            assert {c['id'] for c in result.failed_clauses} == ({'minimum_age' if fact == 'age_years' else fact} if value in denied else set())
            assert result.citations


def test_metadata_notes_and_catalog():
    assert PACK['drug'] == dict(name='Isturisa', generic_name='osilodrostat', therapeutic_class='cortisol-synthesis-inhibitor')
    assert PACK['encoding_status'] == 'partial'
    assert PACK['source']['effective_date'] == '2021-11-01'
    assert PACK['source']['citation'] == 'https://health.alaska.gov/media/xlgbkhpw/202109-isturisa_criteria_2021.pdf'
    assert (ROOT / PACK['source']['criteria_pdf']).exists()
    assert PACK['max_units'] is None and PACK['alternatives'] == ['korlym']
    assert len(PACK['criteria']) == 10
    assert 'inferred_required_facts' not in PACK
    assert {f for c in PACK['criteria'] for f in c['required_facts']} == set(FACTS)
    for phrase in ['3 months', '6 months', 'THREE of five', 'upper limit of normal', 'cortisol levels within normal limits', 'no symptoms consistent', 'no evidence or symptoms of hypocortisolism', 'no evidence of disease progression', '30-day supply', '60 mg/day', 'QTc', 'hepatic', 'hypokalemia', 'hypertension', 'edema', 'hirsutism', 'Version 1', '7/6/2021', '9/17/21', '11/1/21', 'manual review']:
        assert phrase in ' '.join(PACK['notes'])
    assert (BASE / 'isturisa.json').read_bytes() == (BASE / 'rule_packs/isturisa.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 137
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 61
    assert catalog['epidiolex']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert status['encoding_partial'] == 137 and status['encoding_text_only'] == 61
        assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
        assert status['next_candidate'] == 'lucemyra'
    assert (BASE / 'ENCODING_STATUS.md').read_bytes() == (BASE.parent / 'ENCODING_STATUS.md').read_bytes()


def test_attestation_scope():
    texts = {c['id']: c['text'] for c in PACK['criteria']}
    for phrase in ['TWO', 'ketoconazole', 'cabergoline', 'metyrapone', 'mitotane', '30 days each', 'failure, contraindication, or intolerance']:
        assert phrase in texts['two_prior_therapies_ge_30_days']
    for phrase in ['not an option', 'repeat surgeries', 'radiation', 'not been curative', 'still requires']:
        assert phrase in texts['surgery_not_option_or_not_curative']
    assert '<150 nmol/24 hours OR 3.5–45 mcg/24 hours' in texts['urine_free_cortisol_obtained']
    assert 'corrected if abnormal before starting' in texts['baseline_potassium_magnesium_corrected_and_monitoring']
    assert 'periodically' in texts['baseline_ecg_and_periodic_monitoring']
    assert 'periodically' in texts['baseline_potassium_magnesium_corrected_and_monitoring']


@pytest.mark.parametrize('specialty', ['none', 'cardiologist', 'yes', True])
def test_unqualified_specialty(specialty):
    result = evaluate(PACK, dict(FACTS, prescriber_specialty=specialty))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['prescriber_specialty']


def test_reciprocal_korlym_alternative():
    korlym = load_rule_pack_catalog()['korlym']
    assert korlym['encoding_status'] == 'partial'
    assert korlym['alternatives'] == ['isturisa']
    assert evaluate(korlym, {}).decision == 'need_info'
