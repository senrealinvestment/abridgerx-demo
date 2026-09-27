"""Alaska Leqembi Version 1 initial eligibility and catalog integration."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
FACTS = {
    'indication': 'alzheimers_disease',
    'age_years': 50,
    'prescriber_specialty': 'neurologist_or_consult',
    'beta_amyloid_confirmed': 'pet_scan',
    'baseline_mri_aria_safety': 'mri_within_1yr_no_siderosis_lt4_microhem_no_gt1cm_hemorrhage',
    'objective_cognitive_impairment': 'documented',
    'cdr_global_score': 'zero_point_five_or_one',
    'mmse_score': 'ge_22',
    'other_dementia_causes_ruled_out': 'ruled_out',
    'not_on_blood_thinners_except_asa_le_81mg': 'no_blood_thinners_or_asa_le_81_only',
    'no_brain_hemorrhage_bleeding_cv_abnormality_6mo': 'none_in_past_6mo',
    'no_significant_systemic_illness_or_infection_30d': 'none_in_past_30d',
    'no_unstable_cardiac_within_1yr': 'no_unstable_angina_mi_advanced_chf_conduction_abn_1yr',
}


def pack():
    return json.loads((BASE / 'leqembi.json').read_text())


@pytest.mark.parametrize('amyloid', ['pet_scan', 'csf_testing'])
def test_pass(amyloid):
    assert evaluate(pack(), dict(FACTS, beta_amyloid_confirmed=amyloid)).decision == 'pass'


@pytest.mark.parametrize('key,value', [
    ('indication', 'yes'), ('indication', 'no'), ('indication', 'unknown'),
    ('indication', 'parkinsons_dementia'), ('age_years', 49.9),
    ('prescriber_specialty', 'other'), ('beta_amyloid_confirmed', 'not_confirmed'),
    ('baseline_mri_aria_safety', 'not_met'),
    ('objective_cognitive_impairment', 'not_documented'),
    ('cdr_global_score', 'other_or_not_documented'),
    ('mmse_score', 'lt_22_or_not_documented'),
    ('other_dementia_causes_ruled_out', 'not_ruled_out'),
    ('not_on_blood_thinners_except_asa_le_81mg', 'other_anticoagulant_or_antiplatelet'),
    ('no_brain_hemorrhage_bleeding_cv_abnormality_6mo', 'present_in_past_6mo'),
    ('no_significant_systemic_illness_or_infection_30d', 'present'),
    ('no_unstable_cardiac_within_1yr', 'history_present'),
])
def test_each_failure(key, value):
    result = evaluate(pack(), {**FACTS, key: value})
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]


@pytest.mark.parametrize('key', FACTS)
def test_missing_fact(key):
    facts = dict(FACTS)
    del facts[key]
    result = evaluate(pack(), facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


def test_ui_and_single_indication():
    p = pack()
    fields = {f['key']: f for f in drug_detail('leqembi')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert fields['indication']['options'] == [{'value': 'alzheimers_disease', 'label': "Alzheimer's disease"}]
    for key, field in fields.items():
        assert field['type'] == 'select'
        assert field['option_source'] == 'fact_ui'
        assert not field.get('free_text')
        assert 'when' not in field
        assert str(FACTS[key]) in [o['value'] for o in field['options']]
    facts = {k: f['options'][0]['value'] for k, f in fields.items()}
    facts['age_years'] = float('50')
    assert evaluate(p, facts).decision == 'pass'
    assert set(evaluate(p, {}).missing_facts) == set(FACTS)


def test_source_metadata_and_notes():
    p = pack()
    assert p['encoding_status'] == 'partial'
    assert p['drug'] == {'name': 'Leqembi', 'generic_name': 'lecanemab-irmb', 'therapeutic_class': 'alzheimers-agents'}
    assert p['source']['effective_date'] == '2023-03-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/zyvamtbd/202301leqembi_criteria_2023.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/202301leqembi_criteria_2023.pdf'
    assert len(p['criteria']) == 13
    assert 'inferred_required_facts' not in p
    notes = ' '.join(p['notes'])
    for phrase in ['Version 1', '1/17/2023', '01/20/2023', '03/01/2023', 'mild cognitive impairment', '14 weeks', 'infusion reactions', 'up to 3 months', 'up to 6 months', '5th dose', '7th and 14th', '10 mg/kg', 'no adverse reactions']:
        assert phrase in notes
    assert 'fewer than 4' in p['fact_ui']['baseline_mri_aria_safety']['label']
    assert 'at least 22' in p['fact_ui']['mmse_score']['label']


def test_catalog_and_alternatives():
    p = pack()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('leqembi') == ('leqembi', p)
    assert (BASE / 'leqembi.json').read_bytes() == (BASE / 'rule_packs/leqembi.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 143
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 55
    assert p['alternatives'] == ['aduhelm', 'kisunla']
    assert catalog['aduhelm']['alternatives'] == ['leqembi', 'kisunla']
    assert catalog['kisunla']['encoding_status'] == 'partial'
    # A class link alone cannot satisfy the peer's distinct required facts.
    assert evaluate(catalog['aduhelm'], FACTS).decision != 'pass'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 143 and status['encoding_text_only'] == 55
    assert status['next_candidate'] == 'baxdela'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert json.loads((BASE.parent / 'ENCODING_STATUS.json').read_text()) == status
    assert (BASE.parent / 'ENCODING_STATUS.md').read_bytes() == (BASE / 'ENCODING_STATUS.md').read_bytes()
