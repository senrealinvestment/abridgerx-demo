"""Alaska Myqorzo source predicates, attestation semantics and artifacts."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'


def pack():
    return json.loads((BASE / 'rule_packs/myqorzotm.json').read_text())


def facts(**changes):
    result = dict.fromkeys(pack()['fact_ui'], True)
    result.update(indication='obstructive_hypertrophic_cardiomyopathy',
                  age_years=18, concomitant_rifampin=False)
    result.update(changes)
    return result


def test_closed_indication_and_age():
    for age in [18, 19, 85]:
        assert evaluate(pack(), facts(age_years=age)).decision == 'pass'
    for age in [0, 17, 17.99]:
        result = evaluate(pack(), facts(age_years=age))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['age_years']
    for indication in ['nonobstructive_hypertrophic_cardiomyopathy', 'heart_failure', 'other', True, False]:
        assert evaluate(pack(), facts(indication=indication)).decision == 'fail'


def test_each_approval_gate_and_rifampin_denial():
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


def test_ui_options_and_source_attestations():
    detail = drug_detail('myqorzotm')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        for option in field['options']:
            patient = _coerce_patient(facts(**{key: option['value']}))
            assert evaluate(pack(), patient).decision == ('pass' if patient[key] == facts()[key] else 'fail')
    for key, terms in {
        'cardiologist_or_consultation': ['cardiologist', 'or in consultation'],
        'lv_wall_thickness_requirement_met': ['≥15 mm', '15 included', 'OR ≥13 mm', '13 included', 'documented familial'],
        'lvef_below_55': ['<55%', '55 excluded'],
        'baseline_lvot_gradient_requirement_met': ['Baseline resting', '≥30 mmHg', '30 included', 'OR baseline', '≥50 mmHg', '50 included', 'provocation', 'Valsalva'],
        'nyha_class_ii_or_iii': ['class II or class III', 'symptoms of heart failure'],
        'beta_blocker_or_non_dhp_ccb_trial_or_contraindication': ['Tried and failed OR', 'documented clinical contraindication', 'beta blocker OR non-dihydropyridine calcium channel blocker', 'maximally tolerated dose'],
    }.items():
        for term in terms:
            assert term in fields[key]['label']


def test_metadata_notes_mirrors_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='MyqorzoTM', generic_name='aficamten', therapeutic_class='cardiac-myosin-inhibitor')
    assert p['source']['effective_date'] == '2026-06-01'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial'
    assert p['max_units'] is None and p['alternatives'] == []
    assert len(p['criteria']) == 9 and 'inferred_required_facts' not in p
    notes = ' '.join(p['notes'])
    for term in ['Version 1', '3/5/2026', '4/17/2026', '6/1/2026', 'systolic dysfunction',
                 'echocardiogram', 'prior to and during', 'CYP2C9', 'CYP3A',
                 '3 months', '12 months', '30 tablets per 30 days', '20 mg/day', 'manual review']:
        assert term in notes
    assert (BASE / 'myqorzotm.json').read_bytes() == (BASE / 'rule_packs/myqorzotm.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('myqorzotm') == ('myqorzotm', p)
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 165
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 33
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (165, 33)
    assert status['next_candidate'] == 'transderm-scop'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for slug in ['transderm-scop']:
        assert catalog[slug]['encoding_status'] == 'text_only'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
