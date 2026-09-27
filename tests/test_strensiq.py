"""Strensiq Version 2: shared HPP criteria and catalog integration."""
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
INDICATIONS = ['perinatal_infantile_onset_hpp', 'juvenile_onset_hpp']
BIOCHEM = ['elevated_urine_pea', 'elevated_serum_plp_no_vit_supplements_1wk', 'elevated_urinary_ppi']
PASSING = dict(
    indication=INDICATIONS,
    prescriber_specialty=['endocrinologist_or_metabolic_specialist_or_consult'],
    hpp_biochem_confirmation=BIOCHEM,
    onset_age_lt_18=['onset_before_age_18'],
    hpp_clinical_manifestations=['present'],
    low_baseline_alp_for_age=['low_alp_adjusted_for_age'],
    alpl_gene_variant=['at_least_one_variant'],
    patient_weight_submitted=['weight_provided'],
    formulation_appropriate_for_weight=['not_80mg_08ml_or_weight_ge_40kg'],
)


def pack():
    return json.loads((BASE / 'rule_packs/strensiq.json').read_text())


def base():
    return {fact: values[0] for fact, values in PASSING.items()}


@pytest.mark.parametrize('indication', INDICATIONS)
@pytest.mark.parametrize('biochem', BIOCHEM)
def test_shared_indications_and_biochemical_alternatives(indication, biochem):
    assert evaluate(pack(), dict(base(), indication=indication, hpp_biochem_confirmation=biochem)).decision == 'pass'


@pytest.mark.parametrize('indication', INDICATIONS)
def test_ui_options_and_missing_facts(indication):
    p = pack()
    fields = {f['key']: f for f in drug_detail('strensiq')['fact_fields']}
    assert set(fields) == set(PASSING)
    ids = {c['required_facts'][0]: c['id'] for c in p['criteria']}
    for fact, field in fields.items():
        assert field['type'] == 'select' and field['free_text'] is False
        assert 'when' not in field
        for option in field['options']:
            value = option['value']
            patient = dict(base(), indication=indication)
            patient[fact] = value
            result = evaluate(p, _coerce_patient(patient))
            expected = 'pass' if value in PASSING[fact] else 'fail'
            assert result.decision == expected, (fact, value)
            if expected == 'fail':
                assert [c['id'] for c in result.failed_clauses] == [ids[fact]]
        for omit in [True, False]:
            patient = dict(base(), indication=indication)
            if omit:
                del patient[fact]
            else:
                patient[fact] = None
            result = evaluate(p, patient)
            assert result.decision == 'need_info'
            assert result.missing_facts == [fact]
    assert set(evaluate(p, {}).missing_facts) == set(PASSING)


@pytest.mark.parametrize('value', ['adult_onset_hpp', 'hpp', 'other', 'yes', 'no', 'unknown', True, False])
def test_closed_indication(value):
    result = evaluate(pack(), dict(base(), indication=value))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == ['indication_fda_labeled']


def test_onset_not_current_age():
    for age in [0, 17, 18, 40, 80]:
        assert evaluate(pack(), dict(base(), age_years=age)).decision == 'pass'
        result = evaluate(pack(), dict(base(), age_years=age, onset_age_lt_18='adult_onset_or_not_documented'))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['onset_age_lt_18']
    assert all('when' not in c for c in pack()['criteria'])


def test_metadata_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='Strensiq', generic_name='asfotase alfa', therapeutic_class='metabolic')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2024-01-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/24qn5d51/strensiq_criteria_20231117_update.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/strensiq_criteria_20231117_update.pdf'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert len(p['criteria']) == 9
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    for text in ['Version 2', '07/15/20', '11/17/2023', '01/01/2024', 'anaphylaxis', 'lipodystrophy', 'rotate injection sites', 'ectopic calcifications', 'ophthalmologic', 'renal ultrasounds', 'up to 3 months', 'up to 12 months', '9 mg/kg/week', 'manual review']:
        assert text in ' '.join(p['notes'])
    assert (BASE / 'strensiq.json').read_bytes() == (BASE / 'rule_packs/strensiq.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['strensiq'] == p
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 138
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 60
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (138, 60)
    assert status['partial_slugs'] == sorted(s for s, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'lybalvi'
    assert catalog[status['next_candidate']]['encoding_status'] == 'text_only'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
