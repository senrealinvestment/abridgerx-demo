"""Hemophilia Factor Program approval criteria, distinct from provider operations."""
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

INDICATIONS = [
    'hereditary_factor_viii_deficiency',
    'hereditary_factor_ix_deficiency',
    'von_willebrand_disease',
    'acquired_hemophilia',
    'other_hemorrhagic_disorder_intrinsic_anticoagulants_antibodies_inhibitors',
]
FACTS = [
    'prescriber_affiliated_with_regional_htc',
    'providers_agree_comply_with_hemophilia_factor_program_soc',
    'treatment_plan_defines_prophylactic_and_ondemand_regimens',
    'patient_continues_infusion_logging',
]


def load_pack():
    return json.loads((BASE / 'rule_packs/clotting-factor.json').read_text())


def patient(indication=INDICATIONS[0]):
    return dict(indication=indication, **dict.fromkeys(FACTS, True))


def test_metadata_scope_and_notes():
    p = load_pack()
    assert p['encoding_status'] == 'partial'
    assert p['drug']['therapeutic_class'] == 'hemophilia'
    assert p['requires_pa'] and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2017-01-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/fwjbepl3/hemophilia-soc-ccfu_hemophiliafactorprogram_201711_pendimp.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/hemophilia-soc-ccfu_hemophiliafactorprogram_201711_pendimp.pdf'
    assert p['alternatives'] == [] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert [c['id'] for c in p['criteria']] == ['indication', *FACTS]
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(patient())
    for c in p['criteria']:
        assert c['citation'] == p['source']['citation']
    notes = ' '.join(p['notes'])
    for text in ['Version 1', '11/17/17', '5/1/2019', '2017-01-01', '3 months',
                 'clinical stability', 'transfer', 'one month supply', 'same claim',
                 '±5%', 'Required Documentation', 'purchasing/reporting', 'Appendices',
                 'manual review', 'hemlibra', 'hympavzi', 'beqvez-tm', 'hemgenix', 'roctavian']:
        assert text in notes


@pytest.mark.parametrize('indication', INDICATIONS)
def test_all_diagnoses_and_shared_approval_requirements(indication):
    p = load_pack()
    assert evaluate(p, patient(indication)).decision == 'pass'
    for fact in FACTS:
        failed = evaluate(p, dict(patient(indication), **{fact: False}))
        assert failed.decision == 'fail'
        assert {c['id'] for c in failed.failed_clauses} == {fact}
        assert failed.citations
    # Age, severity, factor levels, and operational attestations are not extra gates.
    for age in [0, 5, 18, 90]:
        assert evaluate(p, dict(patient(indication), age_years=age,
                               diagnosis_confirmation=False, annual_certification=False)).decision == 'pass'


@pytest.mark.parametrize('value', ['other', 'hemophilia', 'hemophilia_a', 'hemophilia_b',
                                 'hemophilia_a_prophylaxis', 'yes', 'no', 'unknown', True, False])
def test_closed_diagnosis(value):
    p = load_pack()
    assert p['criteria'][0]['predicate'] == dict(op='in', fact='indication', values=INDICATIONS)
    result = evaluate(p, patient(value))
    assert result.decision == 'fail'
    assert {c['id'] for c in result.failed_clauses} == {'indication'}


def test_missing_facts():
    p = load_pack()
    assert set(evaluate(p, {}).missing_facts) == set(patient())
    for fact in patient():
        data = patient()
        del data[fact]
        result = evaluate(p, data)
        assert result.decision == 'need_info'
        assert result.missing_facts == [fact]


def test_ui_round_trip():
    p = load_pack()
    detail = drug_detail('clotting-factor')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(patient())
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    for fact, field in fields.items():
        assert field['type'] == 'select' and field['option_source'] == 'fact_ui'
        assert not field.get('free_text')
        for option in field['options']:
            result = evaluate(p, _coerce_patient(dict(patient(), **{fact: option['value']})))
            assert result.decision == ('fail' if option['value'] == 'false' else 'pass')


def test_catalog_mirror_bundles_and_duplicate():
    p = load_pack()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('clotting-factor') == ('clotting-factor', p)
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'clotting-factor.json').read_bytes() == (BASE / 'rule_packs/clotting-factor.json').read_bytes()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 181
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 17
    assert catalog['hemophilia']['encoding_status'] == 'text_only'
    assert evaluate(catalog['hemophilia'], patient()).decision == 'need_info'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (181, 17)
    assert status['next_candidate'] == 'oral-benzodiazepines'
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
