"""Hemlibra Alaska Medicaid Version 1 criteria and catalog integration."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/alaska/parsed'
sys.path.insert(0, str(ROOT / 'src'))

from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog


def load_pack():
    return json.loads((BASE / 'rule_packs/hemlibra.json').read_text())


def _base():
    return dict(
        indication='hemophilia_a_prophylaxis',
        fviii_deficiency_confirmed='confirmed_by_coagulation_testing',
        prescriber_specialty='hematologist_or_hemophilia_specialist_or_consult',
        iti_combination_status='not_used_with_iti',
        therapy_intent='routine_prophylaxis_prevent_or_reduce_bleeds',
        bleed_log_agreement='agrees_maintain_bleed_log',
    )


def test_metadata_and_notes():
    p = load_pack()
    assert p['drug'] == dict(name='Hemlibra', generic_name='emicizumab-kxwh', therapeutic_class='hemophilia')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2019-06-10'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/rbhparp4/ac_20194hemlibra_criteria_approved_20190419.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/ac_20194hemlibra_criteria_approved_20190419.pdf'
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 6
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(_base())
    notes = ' '.join(p['notes'])
    for text in ['Version: 1', '03/14/2019', '04/19/2019', '06/10/2019',
                 'newborn and older', '3 months', '12 months', 'spontaneous bleeds',
                 'neutralizing antibodies', '3 mg/kg', '4 weeks', '1.5 mg/kg',
                 '2 weeks', '6 mg/kg', 'TMA', 'AKI', 'manual review']:
        assert text in notes


def test_closed_indication_and_invalid_values():
    p = load_pack()
    assert p['criteria'][0]['predicate'] == dict(op='in', fact='indication', values=['hemophilia_a_prophylaxis'])
    assert [o['value'] for o in p['fact_ui']['indication']['options']] == ['hemophilia_a_prophylaxis']
    for value in ['yes', 'no', 'unknown', True, False, 'other', 'hemophilia_b']:
        result = evaluate(p, dict(_base(), indication=value))
        assert result.decision == 'fail'
        assert {c['id'] for c in result.failed_clauses} == {'indication_fda_labeled'}


def test_approval_failures_and_ui_round_trip():
    p = load_pack()
    detail = drug_detail('hemlibra')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(_base())
    for fact, field in fields.items():
        assert field['type'] == 'select' and field['option_source'] == 'fact_ui'
        assert not field.get('free_text')
        for option in field['options']:
            value = option['value']
            result = evaluate(p, _coerce_patient(dict(_base(), **{fact: value})))
            assert result.decision == ('pass' if value == _base()[fact] else 'fail')
            if value != _base()[fact]:
                assert {c['id'] for c in result.failed_clauses} == {fact}
                assert result.citations


def test_newborn_children_and_adults_without_age_gate():
    p = load_pack()
    assert 'age_years' not in p['fact_ui']
    assert evaluate(p, _base()).decision == 'pass'
    for age in [0, 0.01, 1, 17, 18, 80]:
        assert evaluate(p, dict(_base(), age_years=age)).decision == 'pass'


def test_missing_facts():
    for fact in _base():
        facts = _base()
        del facts[fact]
        result = evaluate(load_pack(), facts)
        assert result.decision == 'need_info'
        assert result.missing_facts == [fact]
    assert set(evaluate(load_pack(), {}).missing_facts) == set(_base())


def test_catalog_bundles_and_status():
    p = load_pack()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('hemlibra') == ('hemlibra', p)
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (BASE / 'hemlibra.json').read_bytes() == (BASE / 'rule_packs/hemlibra.json').read_bytes()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 38
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 160
    assert catalog['soliris']['encoding_status'] == 'partial'
    assert catalog['praluent']['encoding_status'] == 'partial'
    assert catalog['actiq']['encoding_status'] == 'text_only'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 38 and status['encoding_text_only'] == 160
    assert status['next_candidate'] == 'actiq'
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
