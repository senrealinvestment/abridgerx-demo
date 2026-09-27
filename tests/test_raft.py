"""Alaska Zulresso source-specific rules, UI and catalog regression checks."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, check
from ui.app import _coerce_patient
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'


def pack():
    return json.loads((BASE / 'rule_packs/raft.json').read_text())


def facts(**changes):
    result = {k: True for k in pack()['fact_ui']}
    result.update(indication='postpartum_depression', age_years=18,
                  active_psychosis=False)
    result.update(changes)
    return result


def test_age_and_closed_indication():
    for age in [18, 19, 65]:
        assert evaluate(pack(), facts(age_years=age)).decision == 'pass'
    for age in [0, 17, 17.9]:
        result = evaluate(pack(), facts(age_years=age))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['age_years']
    for indication in ['major_depressive_disorder', 'other', 'yes', True, False]:
        assert evaluate(pack(), facts(indication=indication)).decision == 'fail'


def test_each_clinical_gate_and_denial():
    for key, value in facts().items():
        if isinstance(value, bool):
            result = evaluate(pack(), facts(**{key: not value}))
            assert result.decision == 'fail'
            assert [c['id'] for c in result.failed_clauses] == [key]


def test_missing_and_null():
    for key in facts():
        for omit in [True, False]:
            patient = facts()
            if omit:
                del patient[key]
            else:
                patient[key] = None
            result = evaluate(pack(), patient)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
    assert set(evaluate(pack(), {}).missing_facts) == set(facts())


def test_ui_and_attestation_semantics():
    detail = drug_detail('raft')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            patient = _coerce_patient(facts(**{key: option['value']}))
            result = evaluate(pack(), patient)
            assert result.decision == ('pass' if patient[key] == facts()[key] else 'fail')
    labels = {k: v['label'] for k, v in fields.items()}
    for key, terms in {
        'major_depressive_episode_dsm5': ['DSM-5'],
        'ham_d_at_least_20': ['≥20', '20 included'],
        'within_6_months_since_delivery': ['≤6 months', '6 months included'],
        'major_depressive_episode_onset_window': ['third trimester', '4 weeks'],
        'antidepressant_trial_or_contraindication_intolerance': ['oral', 'maximally indicated dose', '6–8 weeks', 'OR', 'contraindication or intolerance', 'two antidepressants', 'two different classes'],
        'rems_certified_healthcare_setting': ['REMS-certified healthcare setting'],
        'patient_weight_submitted': ['weight is submitted'],
        'breastfeeding_requirement_met': ['not lactating or actively breastfeeding', 'initiation and during treatment', 'OR', 'temporarily stop giving breastmilk'],
    }.items():
        for term in terms:
            assert term in labels[key]


def test_metadata_notes_and_artifacts():
    p = pack()
    assert p['drug'] == dict(name='Zulresso', generic_name='brexanolone', therapeutic_class='gaba-a-modulator')
    assert p['source']['effective_date'] == '2022-06-01'
    assert p['source']['list'] == 'Zulresso Criteria'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial'
    assert p['alternatives'] == ['zurzuvae'] and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 12
    notes = ' '.join(p['notes'])
    for term in ['Version 1', '2/8/2022', '4/15/2022', '6/1/2022', '60-hour infusion',
                 'weight-based', 'J1632', 'sedation', 'loss of consciousness', 'hypoxia',
                 'pulse oximetry', 'ESRD', 'suicidal thoughts', 'manual review']:
        assert term in notes
    assert (BASE / 'raft.json').read_bytes() == (BASE / 'rule_packs/raft.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('raft') == ('raft', p)
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 117
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 81
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (117, 81)
    assert status['next_candidate'] == 'rhapsido'
    assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status'] == 'partial')
    for slug in ['rhapsido']:
        assert catalog[slug]['encoding_status'] == 'text_only'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()


def test_reciprocal_alternative_requires_peer_eligibility():
    catalog = load_rule_pack_catalog()
    assert catalog['zurzuvae']['alternatives'] == ['raft']
    patient = facts(active_psychosis=True)
    assert check(pack(), patient, catalog).alternatives[0]['verification'] == 'evaluate_need_info'
    patient.update(within_12_months_since_delivery=True,
                   antidepressant_trial_or_all_contraindicated=True,
                   current_renal_and_liver_labs_within_60_days=True,
                   egfr_at_least_15=True,
                   prior_zulresso_or_zurzuvae_current_pregnancy=False)
    assert check(pack(), patient, catalog).alternatives[0]['verification'] == 'evaluate_pass'
    patient['egfr_at_least_15'] = False
    assert check(pack(), patient, catalog).alternatives == []
