"""Redemplo FCS eligibility, closed diagnostic routes, and catalog integration."""
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
ROUTES = ['biallelic_pathogenic_variants', 'moulin_score_ge_10', 'nafcs_score_ge_45']
SPECIALTIES = ['cardiologist', 'endocrinologist', 'cardiologist_consult', 'endocrinologist_consult']
BOOLS = ['conventional_tg_lowering_therapy_failed', 'secondary_hypertriglyceridemia_ruled_out',
         'low_fat_diet_attested', 'no_concomitant_olezarsen']


def pack():
    return json.loads((BASE / 'rule_packs/redemplo.json').read_text())


def patient():
    return dict(indication='familial_chylomicronemia_syndrome', age_years=18,
                prescriber_specialty='cardiologist', fcs_confirmed_by=ROUTES[0],
                **dict.fromkeys(BOOLS, True))


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('specialty', SPECIALTIES)
def test_qualifying_routes(route, specialty):
    assert evaluate(pack(), dict(patient(), fcs_confirmed_by=route,
                                prescriber_specialty=specialty)).decision == 'pass'


def test_missing_and_null():
    assert set(evaluate(pack(), {}).missing_facts) == set(patient())
    for key in patient():
        for null in [False, True]:
            facts = patient()
            if null:
                facts[key] = None
            else:
                del facts[key]
            result = evaluate(pack(), facts)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]


@pytest.mark.parametrize('key', BOOLS)
def test_failed_gate(key):
    result = evaluate(pack(), dict(patient(), **{key: False}))
    assert result.decision == 'fail'
    assert [c['id'] for c in result.failed_clauses] == [key]


@pytest.mark.parametrize('key', ['indication', 'fcs_confirmed_by', 'prescriber_specialty'])
@pytest.mark.parametrize('value', ['other', 'not_met', 'yes', 'no', True, False])
def test_closed_values(key, value):
    assert evaluate(pack(), dict(patient(), **{key: value})).decision == 'fail'


@pytest.mark.parametrize('age,decision', [(17, 'fail'), (17.99, 'fail'), (18, 'pass'), (90, 'pass')])
def test_age_boundary(age, decision):
    assert evaluate(pack(), dict(patient(), age_years=age)).decision == decision


def test_ui_round_trip_and_source_semantics():
    fields = {f['key']: f for f in drug_detail('redemplo')['fact_fields']}
    assert set(fields) == set(patient())
    passing = dict(indication={'familial_chylomicronemia_syndrome'}, age_years={'18'},
                   prescriber_specialty=set(SPECIALTIES), fcs_confirmed_by=set(ROUTES))
    for key, field in fields.items():
        assert field['type'] == 'select' and field['free_text'] is False
        for option in field['options']:
            val = option['value']
            facts = _coerce_patient(dict(patient(), **{key: val}))
            assert evaluate(pack(), facts).decision == ('pass' if val in passing.get(key, {'yes'}) else 'fail')
    assert {o['value'] for o in fields['indication']['options']} == passing['indication']
    for term in ['biallelic pathogenic', 'LPL', 'APOA5', 'APOC2', 'LMF1', '≥10', '≥45']:
        assert term in fields['fcs_confirmed_by']['label']
    assert 'failed to achieve a TG reduction >20% from baseline' in fields[BOOLS[0]]['label']
    assert 'not currently and will not' in fields['no_concomitant_olezarsen']['label']


def test_metadata_mirror_catalog():
    p = pack()
    assert p['drug'] == dict(name='Redemplo', generic_name='plozasiran', therapeutic_class='apoc3-sirna')
    assert p['source']['effective_date'] == '2026-06-01'
    source = json.loads((BASE / 'criteria_text/redemplo.json').read_text())
    assert p['source']['citation'] == source['source_url']
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['encoding_status'] == 'partial' and len(p['criteria']) == 8
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    notes = ' '.join(p['notes'])
    for term in ['≥20g', '15%–20%', '3 months', '12 months', '25mg/0.5ml', '84 days',
                 'exactly 20%', 'hyperglycemia', 'headache', 'nausea', 'injection site', 'manual review']:
        assert term in notes
    assert (BASE / 'redemplo.json').read_bytes() == (BASE / 'rule_packs/redemplo.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['redemplo'] == p
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 155
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 43
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (155, 43)
    assert status['next_candidate'] == 'nizoral'
    assert catalog['opsumit']['encoding_status'] == 'partial'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
