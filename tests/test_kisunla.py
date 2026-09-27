"""Alaska Kisunla Version 1 initial eligibility and catalog integration."""
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
    'mmse_score': '20_to_28',
    'amyloid_plaque_not_below_stop_thresholds': 'pass',
    'other_dementia_causes_ruled_out': 'ruled_out',
    'not_concurrent_other_anti_amyloid_immunotherapy': 'pass',
    'no_brain_hemorrhage_bleeding_cv_abnormality_6mo': 'none_in_past_6mo',
    'no_significant_systemic_illness_or_infection_30d': 'none_in_past_30d',
    'no_unstable_cardiac_within_1yr': 'no_unstable_angina_mi_advanced_chf_conduction_abn_1yr',
}


def pack():
    return json.loads((BASE / 'kisunla.json').read_text())


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
    ('mmse_score', 'outside_or_not_documented'),
    ('mmse_score', 'ge_22'), ('mmse_score', 'gte_24'),
    ('amyloid_plaque_not_below_stop_thresholds', 'fail'),
    ('other_dementia_causes_ruled_out', 'not_ruled_out'),
    ('not_concurrent_other_anti_amyloid_immunotherapy', 'fail'),
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
    fields = {f['key']: f for f in drug_detail('kisunla')['fact_fields']}
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
    assert p['drug'] == {'name': 'Kisunla', 'generic_name': 'donanemab-azbt', 'therapeutic_class': 'alzheimers-agents'}
    assert p['source']['effective_date'] == '2025-01-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/h0bbdmsn/kisunla_criteria_2024.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/kisunla_criteria_2024.pdf'
    assert len(p['criteria']) == 14
    assert 'inferred_required_facts' not in p
    notes = ' '.join(p['notes'])
    for phrase in ['Version 1', '10/7/2024', '11/15/2024', '01/01/2025', 'mild cognitive impairment', '24 weeks', 'ApoE ε4', 'infusion reactions', 'up to 3 months', 'up to 6 months', 'ARIA mitigation protocol', '1400 mg', 'no adverse reactions']:
        assert phrase in notes
    assert 'fewer than 4' in p['fact_ui']['baseline_mri_aria_safety']['label']
    assert 'between 20 and 28' in p['fact_ui']['mmse_score']['label']


def test_catalog_and_alternatives():
    p = pack()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('kisunla') == ('kisunla', p)
    assert (BASE / 'kisunla.json').read_bytes() == (BASE / 'rule_packs/kisunla.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 105
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 93
    assert p['alternatives'] == ['leqembi', 'aduhelm']
    assert catalog['aduhelm']['alternatives'] == ['leqembi', 'kisunla']
    assert catalog['kisunla']['encoding_status'] == 'partial'
    # A class link alone cannot satisfy the peer's distinct required facts.
    assert evaluate(catalog['aduhelm'], FACTS).decision != 'pass'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 105 and status['encoding_text_only'] == 93
    assert status['next_candidate'] == 'raft'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert json.loads((BASE.parent / 'ENCODING_STATUS.json').read_text()) == status
    assert (BASE.parent / 'ENCODING_STATUS.md').read_bytes() == (BASE / 'ENCODING_STATUS.md').read_bytes()


def test_peer_links_and_distinct_gates():
    catalog = load_rule_pack_catalog()
    for slug in ['leqembi', 'aduhelm']:
        assert 'kisunla' in catalog[slug]['alternatives']
        assert evaluate(catalog[slug], FACTS).decision != 'pass'
    p = pack()
    assert 'not_on_blood_thinners_except_asa_le_81mg' not in p['fact_ui']
    assert [o['value'] for o in p['fact_ui']['mmse_score']['options']] == ['20_to_28', 'outside_or_not_documented']
    gate = next(c for c in p['criteria'] if c['id'] == 'amyloid_plaque_not_below_stop_thresholds')
    assert '<11 Centiloids on a single PET' in gate['text']
    assert '<25 Centiloids on two consecutive PET' in gate['text']
    for c in p['criteria']:
        assert c['citation'].startswith(p['source']['citation'] + '#')
