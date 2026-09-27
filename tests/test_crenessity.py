"""Crenessity eligibility, replacement-dose denial and catalog integration."""
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
INDICATION = 'classic_congenital_adrenal_hyperplasia'
CONFIRMATIONS = ['elevated_17_ohp', 'cyp21a2_mutation_consistent_with_cah',
                 'positive_newborn_screen_confirmatory_second_tier', 'cosyntropin_stimulation_test']
ATTESTATIONS = ['currently_receiving_glucocorticoids_for_cah', 'prescribed_with_glucocorticoids',
                'glucocorticoids_at_or_above_physiological_replacement']


def pack():
    return json.loads((BASE / 'rule_packs/crenessity.json').read_text())


def facts(**changes):
    return dict(dict(indication=INDICATION, age_years=4, prescriber_specialty='endocrinologist',
                     classic_cah_confirmation=CONFIRMATIONS[0], **dict.fromkeys(ATTESTATIONS, True)), **changes)


@pytest.mark.parametrize('confirmation', CONFIRMATIONS)
@pytest.mark.parametrize('specialty', ['endocrinologist', 'endocrinologist_consult'])
@pytest.mark.parametrize('age', [4, 5, 18, 80])
def test_approval(confirmation, specialty, age):
    assert evaluate(pack(), facts(classic_cah_confirmation=confirmation,
                                 prescriber_specialty=specialty, age_years=age)).decision == 'pass'


@pytest.mark.parametrize('key,value', [
    ('age_years', 0), ('age_years', 3), ('age_years', 3.99),
    *[(k, False) for k in ATTESTATIONS],
    *[('indication', v) for v in ['nonclassic_congenital_adrenal_hyperplasia', 'other', 'yes', True, False]],
    *[('classic_cah_confirmation', v) for v in ['not_met', 'yes', 'unknown', True, False]],
    ('prescriber_specialty', 'other'), ('prescriber_specialty', 'pediatrician'),
])
def test_denials(key, value):
    r = evaluate(pack(), facts(**{key: value}))
    assert r.decision == 'fail'
    assert [c['id'] for c in r.failed_clauses] == ['indication_fda_labeled' if key == 'indication' else key]


def test_missing_and_null():
    for key in facts():
        for omit in [True, False]:
            patient = facts()
            if omit:
                del patient[key]
            else:
                patient[key] = None
            r = evaluate(pack(), patient)
            assert r.decision == 'need_info'
            assert r.missing_facts == [key]
    assert set(evaluate(pack(), {}).missing_facts) == set(facts())


def test_ui():
    detail = drug_detail('crenessity')
    assert detail['can_evaluate'] and detail['criteria_text']['extracted_text']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert fields['age_years']['type'] == 'select'
    assert [o['value'] for o in fields['indication']['options']] == [INDICATION]
    assert {o['value'] for o in fields['classic_cah_confirmation']['options']} == set(CONFIRMATIONS) | {'not_met'}
    for key, field in fields.items():
        if key == 'age_years':
            assert {o['value'] for o in field['options']} == {'0', '4'}
            for option in field['options']:
                patient = _coerce_patient(facts(age_years=option['value']))
                assert evaluate(pack(), patient).decision == ('pass' if option['value'] == '4' else 'fail')
            continue
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            value = option['value']
            patient = _coerce_patient(facts(**{key: value, 'age_years': '4'}))
            assert evaluate(pack(), patient).decision == ('fail' if value in ['no', 'not_met', 'other'] else 'pass')


def test_metadata_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='Crenessity', generic_name='crinecerfont', therapeutic_class='crf1-antagonist')
    assert p['source']['effective_date'] == '2025-06-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/qyggj1kd/crenessity_criteria_2025.pdf'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial' and len(p['criteria']) == 7
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert next(c['predicate'] for c in p['criteria'] if c['id'] == 'age_years') == dict(op='gte', fact='age_years', value=4)
    notes = ' '.join(p['notes'])
    for term in ['Version 1', '03/10/2025', '04/18/2025', '06/01/2025', 'adrenal crisis',
                 'moderate or strong CYP3A4 inducer', 'initial approval up to 3 months',
                 'reauthorization up to one year', 'reduction in glucocorticoid daily dose',
                 'reduction in serum androstenedione', '34 day supply at FDA approved dose', 'manual review']:
        assert term in notes
    assert (BASE / 'crenessity.json').read_bytes() == (BASE / 'rule_packs/crenessity.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['crenessity'] == p
    assert catalog['redemplo']['encoding_status'] == 'partial'
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 101
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 97
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (101, 97)
    assert status['next_candidate'] == 'hetlioz'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
