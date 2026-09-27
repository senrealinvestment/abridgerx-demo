"""Amitiza/Linzess Alaska Medicaid Version 2 predicates and artifact checks."""
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
INDICATIONS = ['chronic_idiopathic_constipation',
               'opioid_induced_constipation_chronic_noncancer_pain', 'ibs_c']
STEP = 'two_of_fiber_stimulant_osmotic_inadequate'


def pack():
    return json.loads((BASE / 'rule_packs/amitiza.json').read_text())


def facts(**changes):
    return dict({'indication': INDICATIONS[0], 'age_years': 18,
                 'failed_two_laxative_groups': STEP}, **changes)


def test_all_indications_age_boundary_and_step():
    for indication in INDICATIONS:
        for age in [18, 19, 65]:
            assert evaluate(pack(), facts(indication=indication, age_years=age)).decision == 'pass'
        for age in [0, 17, 17.9]:
            result = evaluate(pack(), facts(indication=indication, age_years=age))
            assert result.decision == 'fail'
            assert [c['id'] for c in result.failed_clauses] == ['minimum_age']
        result = evaluate(pack(), facts(indication=indication, failed_two_laxative_groups='not_met'))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['failed_two_laxative_groups']


def test_closed_choices():
    for invalid in ['yes', 'no', 'unknown', True, False, 'pediatric_constipation', 'other']:
        result = evaluate(pack(), facts(indication=invalid))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['indication_fda_labeled']
    for invalid in ['yes', True, 'fiber', 'stimulant', 'osmotic', 'unknown']:
        assert evaluate(pack(), facts(failed_two_laxative_groups=invalid)).decision == 'fail'


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


def test_ui_selects_and_coercion():
    detail = drug_detail('amitiza')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(facts()) == set(pack()['fact_ui'])
    for key, field in fields.items():
        assert field['type'] == 'select'
        assert not field.get('free_text')
        assert field['options'] == pack()['fact_ui'][key]['options']
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    assert [o['value'] for o in fields['failed_two_laxative_groups']['options']] == [STEP, 'not_met']
    for indication in INDICATIONS:
        patient = facts(indication=indication, age_years='18')
        assert evaluate(pack(), _coerce_patient(patient)).decision == 'pass'
        for key, value in [('age_years', '0'), ('failed_two_laxative_groups', 'not_met')]:
            assert evaluate(pack(), _coerce_patient(dict(patient, **{key: value}))).decision == 'fail'


def test_metadata_and_manual_review_notes():
    p = pack()
    assert p['drug']['name'] == 'Amitiza/Linzess'
    assert p['drug']['generic_name'] == 'lubiprostone / linaclotide'
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2019-06-10'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/lwcnvd3j/amitiza_and_linzess_pa.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/amitiza_and_linzess_pa.pdf'
    assert p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 3
    assert {c['predicate']['fact'] for c in p['criteria']} == set(facts())
    notes = ' '.join(p['notes'])
    for text in ['Version 2', '11/15/2013', '09/19/2014', 'women ≥18', 'Amitiza only',
                 'medical record', 'dates of trial', 'diphenylheptane', 'methadone',
                 '12 months', '2 capsules/day', '290mcg', '145mcg', 'manual review']:
        assert text in notes


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('amitiza') == ('amitiza', pack())
    assert (BASE / 'amitiza.json').read_bytes() == (BASE / 'rule_packs/amitiza.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 107
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 91
    assert catalog['anzupgo']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (107, 91)
    assert status['next_candidate'] == 'corlanor'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
