"""Alaska Praluent/Repatha: clinical gates, labeled age floors and catalog integrity."""
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
INDICATIONS = ['primary_hypercholesterolemia_ldl_gte_190',
               'familial_hypercholesterolemia', 'ascvd_risk_score_gte_20']


def pack():
    return json.loads((BASE / 'rule_packs/praluent.json').read_text())


def facts_for(indication):
    return dict(indication=indication, product='praluent', age_years=18,
                prescriber_specialty='cardiologist_or_consult',
                statin_step='high_potency_max_tolerated_12wk_failure',
                ldl_above_target='ascvd_ldl_gte_70',
                baseline_ldl_and_total_cholesterol_provided='both_provided',
                not_concurrent_other_pcsk9='not_combined')


def test_products_indications_age_boundaries_and_ui():
    p = pack()
    fields = {f['key']: f for f in drug_detail('praluent')['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert {o['value'] for o in fields['indication']['options']} == set(INDICATIONS)
    assert {o['value'] for o in fields['product']['options']} == {'praluent', 'repatha'}
    assert fields['age_years']['option_style'] == 'age_bands'
    for f in fields.values():
        assert f['type'] == 'select' and not f.get('free_text')
    for indication in INDICATIONS:
        for product in ('praluent', 'repatha'):
            minimum = (8 if product == 'praluent' else 10) if indication == 'familial_hypercholesterolemia' else 18
            ages = [0, minimum - 0.01, minimum, 80]
            ages += [_coerce_patient({'age_years': o['value']})['age_years'] for o in fields['age_years']['options']]
            for age in ages:
                result = evaluate(p, dict(facts_for(indication), product=product, age_years=age))
                assert result.decision == ('pass' if age >= minimum else 'fail'), result
                assert {c['id'] for c in result.failed_clauses} == (set() if age >= minimum else {'fda_labeled_age'})
                assert result.citations


def test_every_shared_gate_and_missing_fact():
    p = pack()
    for indication in INDICATIONS:
        for product in ('praluent', 'repatha'):
            facts = dict(facts_for(indication), product=product)
            for fact in facts:
                missing = facts.copy()
                del missing[fact]
                result = evaluate(p, missing)
                assert result.decision == 'need_info', (fact, result)
                assert result.missing_facts == [fact], result
            for fact in set(facts) - {'indication', 'product', 'age_years'}:
                clause = next(c for c in p['criteria'] if c['id'] == fact)
                predicate = clause['predicate']
                allowed = predicate.get('values', [predicate.get('value')])
                for option in p['fact_ui'][fact]['options']:
                    result = evaluate(p, dict(facts, **{fact: option['value']}))
                    expected = 'pass' if option['value'] in allowed else 'fail'
                    assert result.decision == expected, (fact, result)
                    assert {c['id'] for c in result.failed_clauses} == (set() if expected == 'pass' else {fact})


def test_closed_lists_reject_invalid_values():
    for fact in ('indication', 'product'):
        for invalid in ('yes', 'no', 'unknown', 'other', True, False):
            result = evaluate(pack(), dict(facts_for(INDICATIONS[0]), **{fact: invalid}))
            assert result.decision == 'fail'
            assert fact in {c['id'] for c in result.failed_clauses}


def test_metadata_and_catalog():
    p = pack()
    assert len(p['criteria']) == 8
    assert p['drug'] == dict(name='Praluent', generic_name='alirocumab', therapeutic_class='pcsk9-inhibitor')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2026-06-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/0qzn3tx2/pcsk9-inhibitor-update_2026.pdf'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert p['max_units'] is None and p['alternatives'] == ['leqvio']
    assert 'inferred_required_facts' not in p
    for text in ('evolocumab', 'Version 3', '4/29/2016', '4/17/2026', '6/1/2026',
                 '3 months', '1 year', '150 mg', '140 mg', '420 mg', '28 days',
                 'Praluent HoFH is adult-only', 'angioedema', 'manual review'):
        assert text in ' '.join(p['notes'])
    assert (BASE / 'praluent.json').read_bytes() == (BASE / 'rule_packs/praluent.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 112
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 86
    for slug in ['actiq', 'andembry']:
        assert catalog[slug]['encoding_status'] == 'partial'
    assert catalog['lemtrada']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 112 and status['encoding_text_only'] == 86
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'uptravi'
    for ext in ('json', 'md'):
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
