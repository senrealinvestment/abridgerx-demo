"""Alaska Lemtrada initial approval, closed diagnosis and catalog regression tests."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PEERS = ['briumvi', 'kesimpta', 'mavenclad', 'mayzent', 'ocrevus']


def pack():
    return json.loads((BASE / 'rule_packs/lemtrada.json').read_text())


def facts(**updates):
    return dict(dict(indication='relapsing_remitting_ms', jcode='j0202',
        ms_dmt_step_two='inadequate_response_two_or_more_ms_drugs',
        lemtrada_rems_all_parties_enrolled='prescriber_patient_pharmacy_facility_enrolled_compliant',
        rems_baseline_labs_acceptable='baseline_labs_acceptable_submitted',
        administering_provider_enrollment='ak_medicaid_hpg_or_medical_physician_aprn',
        not_home_infusion_therapy=True, not_concurrent_ms_dmt=True,
        hiv_status='negative', tuberculosis_status='tested_negative'), **updates)


def test_metadata_and_source_gaps():
    p = pack()
    assert p['drug'] == dict(name='Lemtrada', generic_name='alemtuzumab', therapeutic_class='ms-disease-modifying')
    assert p['source']['effective_date'] == '2016-10-03'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/l20irikz/ccfu_multiplesclerosis_lemtrada_20161003.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/ccfu_multiplesclerosis_lemtrada_20161003.pdf'
    assert p['encoding_status'] == 'partial' and p['requires_pa']
    assert p['max_units'] is None and p['pdl_status'] == 'unknown'
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 10
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts())
    assert 'age_years' not in p['fact_ui']
    notes = ' '.join(p['notes'])
    for text in ['3/3/2016', '3/25/2016', '10/3/2016', 'Version: 1', '1 year',
                 '5 vials (6 mL)', '3 vials (3.6 mL)', 'positive clinical response',
                 'current labs', 'training', 'ongoing monitoring', 'on-site equipment',
                 'verifying patient authorization', 'manual review']:
        assert text in notes


def test_rrms_only_without_age_gate():
    assert evaluate(pack(), facts()).decision == 'pass'
    for value in ['clinically_isolated_syndrome', 'active_secondary_progressive_ms',
                  'secondary_progressive_ms', 'primary_progressive_ms', 'other',
                  'yes', 'no', 'unknown', True, False]:
        result = evaluate(pack(), facts(indication=value))
        assert result.decision == 'fail'
        assert {c['id'] for c in result.failed_clauses} == {'indication_fda_labeled'}


def test_each_approval_denial_and_missing_fact():
    for key, value in dict(jcode='other_or_missing', ms_dmt_step_two='none',
            lemtrada_rems_all_parties_enrolled='not_fully_enrolled',
            rems_baseline_labs_acceptable='labs_not_acceptable_or_missing',
            administering_provider_enrollment='not_enrolled',
            not_home_infusion_therapy=False, not_concurrent_ms_dmt=False,
            hiv_status='positive_or_not_tested', tuberculosis_status='positive_or_not_tested').items():
        result = evaluate(pack(), facts(**{key: value}))
        assert result.decision == 'fail'
        assert {c['id'] for c in result.failed_clauses} == {key}
        assert result.citations == [pack()['source']['citation']]
    for key in facts():
        patient = facts()
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert key in result.missing_facts


def test_ui_closed_selects_and_coercion():
    detail = drug_detail('lemtrada')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == ['relapsing_remitting_ms']
    raw = {k: 'yes' if v is True else v for k, v in facts().items()}
    assert _coerce_patient(raw) == facts()
    for key, field in fields.items():
        assert field['type'] == 'select' and field['option_source'] == 'fact_ui'
        for option in field['options']:
            patient = _coerce_patient(dict(raw, **{key: option['value']}))
            expected = 'pass' if option['value'] == raw[key] else 'fail'
            assert evaluate(pack(), patient).decision == expected


def test_catalog_mirrors_alternatives_and_scope():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 67
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 131
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert catalog['lemtrada']['alternatives'] == PEERS
    for slug in ['lemtrada'] + PEERS:
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / f'rule_packs/{slug}.json').read_bytes()
        assert catalog[slug]['alternatives'] == sorted(set(['lemtrada'] + PEERS) - {slug})
    for slug in ['actiq', 'andembry']:
        assert catalog[slug]['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 67 and status['encoding_text_only'] == 131
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'kalydeco'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('lemtrada tests ok')
