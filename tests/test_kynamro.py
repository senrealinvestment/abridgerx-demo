"""Kynamro approval attestations and catalog integrity; Kynamro is a reciprocal partial alternative."""
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


def pack():
    return json.loads((BASE / 'rule_packs/kynamro.json').read_text())


def facts():
    return dict(indication='homozygous_familial_hypercholesterolemia', age_years=18,
                hofh_confirmation_submitted=True,
                boxed_warnings_discussed_and_labs_monitored=True,
                current_lipid_lowering_treatments_submitted=True,
                pregnancy_test_status='negative_test_obtained', low_fat_diet_documented=True)


def test_approval_missing_false_and_ui_options():
    p, base = pack(), facts()
    assert evaluate(p, base).decision == 'pass'
    for key in base:
        missing = base.copy()
        del missing[key]
        result = evaluate(p, missing)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
        pred = next(c['predicate'] for c in p['criteria'] if c['id'] == key)
        for option in p['fact_ui'][key]['options']:
            value = _coerce_patient({key: option['value']})[key]
            allowed = (value >= 18 if key == 'age_years' else
                       value in pred['values'] if pred['op'] == 'in' else value is True)
            result = evaluate(p, dict(base, **{key: value}))
            assert result.decision == ('pass' if allowed else 'fail')
            assert {c['id'] for c in result.failed_clauses} == (set() if allowed else {key})
            assert result.citations == [p['source']['citation']]
    for invalid in ('heterozygous_familial_hypercholesterolemia', 'clinical_ascvd', 'other', True, False):
        assert evaluate(p, dict(base, indication=invalid)).decision == 'fail'
    for age in (0, 17, 17.99, 18, 90):
        assert evaluate(p, dict(base, age_years=age)).decision == ('pass' if age >= 18 else 'fail')
    for invalid in ('unknown', 'pregnant', True, False):
        assert evaluate(p, dict(base, pregnancy_test_status=invalid)).decision == 'fail'


def test_metadata_and_closed_fields():
    p = pack()
    fields = {f['key']: f for f in drug_detail('kynamro')['fact_fields']}
    assert set(fields) == set(facts()) == set(p['fact_ui'])
    assert [o['value'] for o in fields['indication']['options']] == [facts()['indication']]
    assert len(p['criteria']) == 7
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert all(c['citation'] == p['source']['citation'] for c in p['criteria'])
    assert p['drug'] == dict(name='Kynamro', generic_name='mipomersen', therapeutic_class='lipotropics')
    assert p['source']['effective_date'] == '1970-01-01'
    assert p['encoding_status'] == 'partial' and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    for phrase in ('11/15/2013', '<20%', '6 months', '12 months', 'tolerance', 'progress notes',
                   'effectiveness', 'four (4)', 'prefilled syringes', 'LDL apheresis', 'cardiovascular', 'manual review'):
        assert phrase in ' '.join(p['notes'])


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 139
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 59
    assert catalog['kynamro']['alternatives'] == ['juxtapid']
    assert catalog['juxtapid']['alternatives'] == ['kynamro']
    assert catalog['juxtapid']['encoding_status'] == 'partial'
    assert len(catalog['juxtapid']['criteria']) == 7
    assert evaluate(catalog['juxtapid'], facts()).decision == 'pass'
    assert (BASE / 'kynamro.json').read_bytes() == (BASE / 'rule_packs/kynamro.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (139, 59)
    assert status['next_candidate'] == 'orexin-receptor-antagonists'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for ext in ('json', 'md'):
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()


def test_next_pack_remains_unencoded():
    p = load_rule_pack_catalog()['orexin-receptor-antagonists']
    assert p['encoding_status'] == 'text_only'
    assert p['criteria'] == []
    assert evaluate(p, facts()).decision == 'need_info'
