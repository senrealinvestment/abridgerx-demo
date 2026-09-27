"""Amrix Version 2: alternate approval paths, shared denials and catalog integrity."""
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
STEP = 'ir_cyclobenzaprine_5_or_10mg_ge_5_days_suboptimal'
IND = 'acute_painful_musculoskeletal_muscle_spasm'


def pack():
    return json.loads((BASE / 'rule_packs/amrix.json').read_text())


def facts(**updates):
    return dict({'pa_override_population': 'standard_outpatient_path', 'indication': IND,
                 'age_years': 18, STEP: True, 'no_hyperthyroidism': True,
                 'not_concurrent_maoi': True}, **updates)


def test_standard_boundaries_and_closed_indication():
    for age in [18, 40, 65]:
        assert evaluate(pack(), facts(age_years=age)).decision == 'pass'
    for age in [0, 17, 17.9, 65.1, 66, 90]:
        assert evaluate(pack(), facts(age_years=age)).decision == 'fail'
    for indication in ['yes', 'no', 'unknown', True, False, 'spasticity', 'cerebral_palsy']:
        assert evaluate(pack(), facts(indication=indication)).decision == 'fail'
    for key in [STEP, 'no_hyperthyroidism', 'not_concurrent_maoi']:
        assert evaluate(pack(), facts(**{key: False})).decision == 'fail'
    for value in ['unknown', 'yes', True]:
        assert evaluate(pack(), facts(pa_override_population=value)).decision == 'fail'


def test_missing_facts():
    for key in facts():
        patient = facts()
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
    result = evaluate(pack(), {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(facts())


def test_override_waives_approval_but_retains_denials():
    patient = {'pa_override_population': 'hospice_or_cancer_or_ltc',
               'no_hyperthyroidism': True, 'not_concurrent_maoi': True}
    result = evaluate(pack(), patient)
    assert result.decision == 'pass' and not result.missing_facts
    assert evaluate(pack(), dict(patient, age_years=90, indication='spasticity',
                                 **{STEP: False})).decision == 'pass'
    for key in ['no_hyperthyroidism', 'not_concurrent_maoi']:
        result = evaluate(pack(), dict(patient, **{key: False}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [key]
        missing = dict(patient)
        del missing[key]
        result = evaluate(pack(), missing)
        assert result.decision == 'need_info' and result.missing_facts == [key]


def test_ui_options_gates_and_coercion():
    detail = drug_detail('amrix')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        assert field['options'] == pack()['fact_ui'][key]['options']
    assert [o['value'] for o in fields['indication']['options']] == [IND]
    for key in ['age_years', 'indication', STEP]:
        assert fields[key]['when'] == {'fact': 'pa_override_population', 'eq': 'standard_outpatient_path'}
    for key in ['pa_override_population', 'no_hyperthyroidism', 'not_concurrent_maoi']:
        assert 'when' not in fields[key]
    for age, decision in [('0', 'fail'), ('18', 'pass'), ('66', 'fail')]:
        patient = facts(age_years=age, **{STEP: 'yes', 'no_hyperthyroidism': 'yes', 'not_concurrent_maoi': 'yes'})
        assert evaluate(pack(), _coerce_patient(patient)).decision == decision


def test_metadata_notes_and_catalog():
    p = pack()
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2014-09-19'
    assert 'inferred_required_facts' not in p and p['alternatives'] == []
    notes = ' '.join(p['notes'])
    for text in ['Version 2', '05/28/2009', '09/19/2014', '2–3 weeks', 'spasticity',
                 'cerebral palsy', '21 capsules / 21 days', 'no refills', 'new PA']:
        assert text in notes
    assert (BASE / 'amrix.json').read_bytes() == (BASE / 'rule_packs/amrix.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 132
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 66
    assert catalog['andembry']['encoding_status'] == 'partial'
    assert catalog['anzupgo']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 132 and status['encoding_text_only'] == 66
    assert status['next_candidate'] == 'h-p-acthar'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
