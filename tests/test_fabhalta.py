"""Fabhalta Alaska Medicaid Version 1 predicates and catalog integration."""
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
STEP = 'failed_or_intolerance_contraindication_complement_inhibitor'
BOOLS = ['pnh_flow_cytometry_confirmed', 'hemoglobin_lt_10_g_dl',
         'baseline_lipid_panel_hb_ldh_documented',
         'encapsulated_bacteria_vaccines_ge_14d_prior',
         'not_combined_with_other_complement_inhibitor',
         'no_unresolved_serious_encapsulated_bacterial_infection']


def load_pack():
    return json.loads((BASE / 'fabhalta.json').read_text())


def _base(**extra):
    facts = dict(indication='paroxysmal_nocturnal_hemoglobinuria', age_years=18,
                 prescriber_specialty='hematologist', **{STEP: 'eculizumab'},
                 **dict.fromkeys(BOOLS, True))
    return dict(facts, **extra)


def _assert_fail(fact, value):
    result = evaluate(load_pack(), _base(**{fact: value}))
    assert result.decision == 'fail', result
    clause = {'indication': 'indication_fda_labeled', 'age_years': 'minimum_age'}.get(fact, fact)
    assert {c['id'] for c in result.failed_clauses} == {clause}
    assert result.citations


def test_metadata_and_notes():
    pack = load_pack()
    assert pack['drug'] == dict(name='Fabhalta', generic_name='iptacopan',
                               therapeutic_class='complement-inhibitor')
    assert pack['encoding_status'] == 'partial'
    assert pack['pdl_status'] == 'unknown'
    assert pack['source']['effective_date'] == '2024-06-01'
    assert pack['source']['citation'] == 'https://health.alaska.gov/media/e3hh5fu3/fabhalta_criteria_2024.pdf'
    assert pack['source']['criteria_pdf'] == 'data/alaska/raw/fabhalta_criteria_2024.pdf'
    assert 'inferred_required_facts' not in pack
    assert len(pack['criteria']) == 10
    assert {f for c in pack['criteria'] for f in c['required_facts']} == set(_base())
    for clause in pack['criteria']:
        if clause['id'] in BOOLS:
            assert clause['predicate'] == dict(op='eq', fact=clause['id'], value=True)
    notes = ' '.join(pack['notes'])
    for text in ['Version 1', '03/13/2024', '04/19/2024', '06/1/2024',
                 '3 months', '12 months', '68 capsules', '34 days',
                 'fatal infections', 'Vaccination does not eliminate', 'hemolysis',
                 '2 weeks', 'CYP2C8', 'manual review']:
        assert text in notes
    assert 'rems' not in pack['fact_ui']


def test_boundaries_and_closed_indication():
    for age in [18, 19, 80]:
        for therapy in ['eculizumab', 'pegcetacoplan', 'ravulizumab']:
            assert evaluate(load_pack(), _base(age_years=age, **{STEP: therapy})).decision == 'pass'
    for age in [0, 17, 17.99]:
        _assert_fail('age_years', age)
    for indication in ['pnh', 'other', 'iga_nephropathy', 'yes', 'no', True, False]:
        _assert_fail('indication', indication)
    for specialty in ['oncologist', 'primary_care', 'other']:
        _assert_fail('prescriber_specialty', specialty)
    for step in ['not_met', 'unknown', 'yes', True]:
        _assert_fail(STEP, step)
    for fact in BOOLS:
        _assert_fail(fact, False)


def test_missing_facts():
    for fact in _base():
        facts = _base()
        del facts[fact]
        result = evaluate(load_pack(), facts)
        assert result.decision == 'need_info'
        assert result.missing_facts == [fact]
    result = evaluate(load_pack(), {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(_base())


def test_selects_and_every_ui_option():
    pack = load_pack()
    detail = drug_detail('fabhalta')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(pack['fact_ui']) == set(_base())
    assert fields['indication']['options'] == [dict(
        value='paroxysmal_nocturnal_hemoglobinuria', label='Paroxysmal nocturnal hemoglobinuria (PNH)')]
    facts = {key: field['options'][0]['value'] for key, field in fields.items()}
    facts['age_years'] = '18'
    assert _coerce_patient(facts) == _base()
    passing = {'indication': {'paroxysmal_nocturnal_hemoglobinuria'},
               'age_years': {'18'}, 'prescriber_specialty': {'hematologist'},
               STEP: {'eculizumab', 'pegcetacoplan', 'ravulizumab'}}
    for fact, field in fields.items():
        assert field['type'] == 'select' and field['option_source'] == 'fact_ui'
        assert not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(pack, _coerce_patient(dict(facts, **{fact: value})))
            assert result.decision == ('pass' if value in passing.get(fact, {'yes'}) else 'fail')


def test_catalog_bundles_mirrors_and_status():
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('fabhalta') == ('fabhalta', pack)
    assert (BASE / 'fabhalta.json').read_bytes() == (BASE / 'rule_packs/fabhalta.json').read_bytes()
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE / 'rule_packs').glob('*.json')}
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 152
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 46
    assert catalog['evkeeza']['encoding_status'] == 'partial'
    assert pack['alternatives'] == ['empaveli', 'soliris']
    for slug in pack['alternatives']:
        assert 'fabhalta' in catalog[slug]['alternatives']
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / f'rule_packs/{slug}.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 152 and status['encoding_text_only'] == 46
    assert status['next_candidate'] == 'marinol'
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
    assert json.loads((BASE.parent / 'ENCODING_STATUS.json').read_text()) == status
    assert (BASE.parent / 'ENCODING_STATUS.md').read_bytes() == (BASE / 'ENCODING_STATUS.md').read_bytes()
