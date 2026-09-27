"""Dojolvi PDF-specific gates, two-of-three confirmation and catalog integration."""
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
PATHWAYS = {'acylcarnitines_and_enzyme', 'acylcarnitines_and_genetic',
            'enzyme_and_genetic', 'all_three'}
SPECIALTIES = {'endocrinologist', 'metabolic_disease_specialist',
               'endocrinologist_or_metabolic_disease_specialist_consult'}


def load_pack():
    return json.loads((BASE / 'rule_packs/dojolvi.json').read_text())


def base():
    return dict(indication='lc_faod',
                lc_faod_molecular_confirmation='acylcarnitines_and_enzyme',
                prescriber_specialty='endocrinologist',
                weight_and_daily_caloric_intake_submitted=True,
                dose_not_exceed_35_percent_daily_caloric_intake=True,
                no_concurrent_other_medium_chain_triglyceride=True)


def test_closed_indication_and_no_invented_age_or_caution_gate():
    pack = load_pack()
    assert evaluate(pack, base()).decision == 'pass'
    for age in [0, 1, 17, 18, 90]:
        assert evaluate(pack, dict(base(), age_years=age)).decision == 'pass'
    for indication in ['other', 'short_chain_faod', 'yes', 'no', True, False]:
        result = evaluate(pack, dict(base(), indication=indication))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['indication_fda_labeled']
    assert 'age_years' not in pack['fact_ui']
    assert not any('lipase' in c['id'] for c in pack['criteria'])


def test_every_ui_option_and_independent_gate():
    pack = load_pack()
    fields = {f['key']: f for f in drug_detail('dojolvi')['fact_fields']}
    assert set(fields) == set(base())
    passing = {'indication': {'lc_faod'},
               'lc_faod_molecular_confirmation': PATHWAYS,
               'prescriber_specialty': SPECIALTIES}
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
    confirmation = fields['lc_faod_molecular_confirmation']
    assert {o['value'] for o in confirmation['options']} == PATHWAYS | {
        'acylcarnitines_only', 'enzyme_only', 'genetic_only', 'none'}
    for invalid in ['yes', True, 'unknown', 'genetic_only']:
        result = evaluate(pack, dict(base(), lc_faod_molecular_confirmation=invalid))
        assert result.decision == 'fail'
    for text in ['at least TWO', 'newborn blood spot or in plasma',
                 'cultured fibroblasts or lymphocytes', 'reporting laboratory',
                 'pathogenic mutation']:
        assert text in pack['fact_ui']['lc_faod_molecular_confirmation']['label']


def test_missing_facts():
    for fact in base():
        for omit in [True, False]:
            facts = base()
            if omit:
                del facts[fact]
            else:
                facts[fact] = None
            result = evaluate(load_pack(), facts)
            assert result.decision == 'need_info'
            assert result.missing_facts == [fact]
    assert set(evaluate(load_pack(), {}).missing_facts) == set(base())


def test_metadata_notes_and_catalog():
    pack = load_pack()
    assert pack['drug'] == dict(name='Dojolvi', generic_name='triheptanoin',
                                therapeutic_class='lipotropics')
    assert pack['encoding_status'] == 'partial'
    assert pack['source'] == dict(
        payer='alaska_medicaid', list='Dojolvi Criteria', effective_date='2021-01-11',
        citation='https://health.alaska.gov/media/3ofdnyp4/202011dojolvi_criteria_2020.pdf',
        criteria_pdf='data/alaska/raw/202011dojolvi_criteria_2020.pdf')
    assert (ROOT / pack['source']['criteria_pdf']).exists()
    assert len(pack['criteria']) == 6
    assert 'inferred_required_facts' not in pack
    assert pack['alternatives'] == [] and pack['max_units'] is None
    notes = ' '.join(pack['notes'])
    for text in ['10/08/20', '11/20/20', '1/11/21', 'at least TWO',
                 'initial approval up to 3 months', 'reauthorization approval up to 12 months',
                 '30 days', '35%', 'Pancreatic Lipase Inhibitors',
                 'reduced clinical effect', 'manual review']:
        assert text in notes
    assert (BASE / 'dojolvi.json').read_bytes() == (BASE / 'rule_packs/dojolvi.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['dojolvi'] == pack
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 95
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 103
    assert catalog['auvelity']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (95, 103)
    assert status['next_candidate'] == 'firazyr'
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
