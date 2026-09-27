"""Nexletol/Nexlizet shared Alaska criteria and catalog integration."""
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
HEFH = 'heterozygous_familial_hypercholesterolemia'
ASCVD = 'established_ascvd'


def pack():
    return json.loads((BASE / 'rule_packs/nexletol.json').read_text())


def facts():
    return dict(indication=HEFH, age_years=18, prescriber_specialty='cardiology',
                statin_step='maximally_tolerated_concomitant',
                ldl_response='reduction_lt_50_percent',
                simvastatin_daily_dose='within_limit_or_not_used',
                pravastatin_daily_dose='within_limit_or_not_used',
                current_pcsk9_inhibitor='not_using')


def test_all_controlled_options_and_missing_facts():
    p = pack()
    for indication in (HEFH, ASCVD):
        f = dict(facts(), indication=indication)
        if indication == ASCVD:
            f['clinical_ascvd_history'] = 'angina'
        assert evaluate(p, f).decision == 'pass'
        for key in f:
            missing = f.copy()
            del missing[key]
            result = evaluate(p, missing)
            assert result.decision == 'need_info'
            assert key in result.missing_facts
        for key in f:
            for option in p['fact_ui'][key]['options']:
                val = _coerce_patient({key: option['value']})[key]
                bad = val in ('none', 'other', 'not_met', 'above_limit', 'using') or (key == 'age_years' and val < 18)
                bad |= key == 'ldl_response' and val == 'no_ascvd_ldl_gt_100' and indication == ASCVD
                # Changing the diagnosis does not fabricate a clinical history.
                expected = 'need_info' if key == 'indication' and val == ASCVD and indication == HEFH else ('fail' if bad else 'pass')
                assert evaluate(p, dict(f, **{key: val})).decision == expected, (key, val)
    assert evaluate(p, {}).decision == 'need_info'


@pytest.mark.parametrize('age,expected', [(0,'fail'),(17.99,'fail'),(18,'pass'),(90,'pass')])
def test_age_boundary(age, expected):
    assert evaluate(pack(), dict(facts(), age_years=age)).decision == expected


@pytest.mark.parametrize('invalid', ['yes','no','unknown','other',True,False,'homozygous_familial_hypercholesterolemia'])
def test_closed_indications(invalid):
    assert evaluate(pack(), dict(facts(), indication=invalid)).decision == 'fail'


def test_shared_products_and_denials():
    for product in ('nexletol', 'nexlizet'):
        f = dict(facts(), product=product)
        assert evaluate(pack(), f).decision == 'pass'
        for key, val in [('simvastatin_daily_dose','above_limit'),('pravastatin_daily_dose','above_limit'),('current_pcsk9_inhibitor','using'),('statin_step','not_met'),('ldl_response','not_met')]:
            r = evaluate(pack(), dict(f, **{key:val}))
            assert r.decision == 'fail'
            assert [c['id'] for c in r.failed_clauses] == [key]
            assert r.citations == [pack()['source']['citation']]
    # No additional history requirement for confirmed HeFH.
    assert evaluate(pack(), dict(facts(), clinical_ascvd_history='none')).decision == 'pass'


def test_ui_metadata_and_catalog():
    p = pack()
    fields = {f['key']:f for f in drug_detail('nexletol')['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert [o['value'] for o in fields['indication']['options']] == [HEFH, ASCVD]
    assert fields['clinical_ascvd_history']['when'] == {'fact':'indication','eq':ASCVD}
    assert p['drug']['therapeutic_class'] == 'acl-inhibitor'
    assert p['source']['effective_date'] == '2020-11-16'
    assert len(p['criteria']) == 9
    assert p['encoding_status'] == 'partial' and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    for phrase in ('<50%', '>70 mg/dL', '>100 mg/dL', '>20 mg', '>40 mg', 'hyperuricemia', 'Tendon rupture', '3 months', '12 months', '30 tablets', 'manual review'):
        assert phrase in ' '.join(p['notes'])
    assert (BASE/'nexletol.json').read_bytes() == (BASE/'rule_packs/nexletol.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == json.loads((BASE/'rule_packs_all.json').read_text())
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status']=='partial' for v in catalog.values()) == 189
    assert sum(v['encoding_status']=='text_only' for v in catalog.values()) == 9
    s = json.loads((BASE/'ENCODING_STATUS.json').read_text())
    assert (s['encoding_partial'],s['encoding_text_only']) == (189,9)
    assert s['next_candidate'] == '2024-2025-season'
    assert catalog['bone-resorption-inhibitors']['encoding_status'] == 'partial'
    for ext in ('json','md'):
        assert (BASE/f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent/f'ENCODING_STATUS.{ext}').read_bytes()
