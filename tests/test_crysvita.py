"""Crysvita Alaska Medicaid Version 1 approval gates and catalog integration."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog


def load_pack():
    return json.loads((ROOT / 'data/alaska/parsed/rule_packs/crysvita.json').read_text())


def base():
    return dict(
        indication='x_linked_hypophosphatemia', age_years=1,
        prescriber_specialty='nephrologist',
        xlh_genetic_and_baseline_fgf23='phex_or_genetic_confirmed_and_baseline_fgf23_obtained',
        baseline_fasting_serum_phosphorus_below_normal_for_age=True,
        calcitriol_plus_oral_phosphate_step='trialed_ge_2_months_with_levels_documented',
        oral_phosphate_and_vitamin_d_analog_discontinued_ge_1_week=True,
        prescriber_agrees_monitor_document_serum_phosphorus=True,
    )


def test_age_and_closed_indication():
    pack = load_pack()
    for age in [0, 0.5, 0.999, 1, 6, 18, 80]:
        result = evaluate(pack, dict(base(), age_years=age))
        assert result.decision == ('pass' if age >= 1 else 'fail')
        if age < 1:
            assert [c['id'] for c in result.failed_clauses] == ['age_fda_labeled']
    for value in ['yes', 'no', 'unknown', True, False, 'other', 'tumor_induced_osteomalacia']:
        result = evaluate(pack, dict(base(), indication=value))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['indication_fda_labeled']


def test_every_ui_option_and_clause():
    pack = load_pack()
    fields = {f['key']: f for f in drug_detail('crysvita')['fact_fields']}
    assert set(fields) == set(base())
    passing = {
        'indication': {'x_linked_hypophosphatemia'}, 'age_years': {'1'},
        'prescriber_specialty': {'nephrologist', 'endocrinologist', 'nephrologist_or_endocrinologist_consult'},
        'xlh_genetic_and_baseline_fgf23': {'phex_or_genetic_confirmed_and_baseline_fgf23_obtained'},
        'calcitriol_plus_oral_phosphate_step': {'trialed_ge_2_months_with_levels_documented', 'contraindication_or_intolerance_with_levels_documented'},
    }
    ids = {c['required_facts'][0]: c['id'] for c in pack['criteria']}
    for fact, field in fields.items():
        assert field['type'] == 'select' and field['free_text'] is False
        for option in field['options']:
            value = option['value']
            result = evaluate(pack, _coerce_patient(dict(base(), **{fact: value})))
            expected = 'pass' if value in passing.get(fact, {'yes'}) else 'fail'
            assert result.decision == expected, (fact, value, result)
            if expected == 'fail':
                assert [c['id'] for c in result.failed_clauses] == [ids[fact]]
    assert fields['indication']['options'] == [{'value': 'x_linked_hypophosphatemia', 'label': 'X-linked hypophosphatemia (XLH)'}]
    assert fields['age_years']['options'] == [{'value': '0', 'label': 'Under 1 year'}, {'value': '1', 'label': '1 year or older'}]


def test_missing_facts():
    for fact in base():
        for missing in [None, 'omit']:
            facts = base()
            if missing == 'omit':
                del facts[fact]
            else:
                facts[fact] = None
            result = evaluate(load_pack(), facts)
            assert result.decision == 'need_info'
            assert result.missing_facts == [fact]
    assert set(evaluate(load_pack(), {}).missing_facts) == set(base())


def test_metadata_notes_and_catalog():
    pack = load_pack()
    assert pack['drug'] == {'name': 'Crysvita', 'generic_name': 'burosumab-twza', 'therapeutic_class': 'biologics'}
    assert pack['encoding_status'] == 'partial'
    assert pack['source']['effective_date'] == '2019-06-10'
    assert pack['source']['citation'] == 'https://health.alaska.gov/media/hmbfuity/20194crysvita_criteria_approved_20190419.pdf'
    assert pack['source']['criteria_pdf'] == 'data/alaska/raw/20194crysvita_criteria_approved_20190419.pdf'
    assert (ROOT / pack['source']['criteria_pdf']).exists()
    assert len(pack['criteria']) == 8
    assert 'inferred_required_facts' not in pack
    assert pack['alternatives'] == [] and pack['max_units'] is None
    notes = ' '.join(pack['notes'])
    for text in ['03/7/2019', '04/19/2019', '06/10/2019', 'severe renal impairment', 'ESRD', 'up to 3 months', 'up to 12 months', 'positive clinical response', '10 mg/ml vial: 2 per 28 days', '20 mg/ml vial: 2 per 28 days', '30 mg/ml vial: 6 per 28 days', 'manual review']:
        assert text in notes
    parsed = ROOT / 'data/alaska/parsed'
    assert (parsed / 'crysvita.json').read_bytes() == (parsed / 'rule_packs/crysvita.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['crysvita'] == pack
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (parsed / 'rule_packs').glob('*.json')}
    with gzip.open(parsed / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 174
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 24
    assert catalog['evkeeza']['encoding_status'] == 'partial'
    status = json.loads((parsed / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 174 and status['encoding_text_only'] == 24
    assert status['next_candidate'] == 'rybix-odt'
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (parsed / name).read_bytes() == (parsed.parent / name).read_bytes()
