"""Alaska Soliris/Ultomiris Version 2: branch, boundary and catalog regressions."""
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
BRANCHES = {
    'ahus': dict(ttp_ruled_out='normal_adamts13_or_plasma_exchange_no_improvement',
                 no_shiga_toxin_e_coli='no_stec_infection',
                 ahus_baseline_labs='one_or_more_ldh_creat_egfr_platelet_or_plasma_exchange'),
    'pnh': dict(pnh_flow_cytometry_confirmed='confirmed_by_flow_cytometry',
                pnh_therapy_indication='thrombotic_event',
                pnh_baseline_labs_all='ldh_and_hemoglobin_and_prbc_transfusion_requirement_documented'),
    'gmg': dict(mgfa_class='ii_iii_or_iv', mg_adl_score='gte_6', achr_antibody='positive',
                qmg_baseline_assessed=True,
                gmg_immunosuppressive_step='inadequate_or_ci_two_or_more_is_agents_12mo'),
    'nmosd': dict(aqp4_antibody='positive_aqp4_igg',
                  nmosd_systemic_step='failure_one_of_aza_mmf_ritux_with_relapse_history',
                  ms_ruled_out='ms_ruled_out'),
}


def pack():
    return json.loads((BASE / 'rule_packs/soliris.json').read_text())


def facts_for(indication):
    return dict(indication=indication, product='soliris', age_years=18,
                meningococcal_vaccine_status='vaccinated_gte_14d_prior',
                prescriber_specialty='hematologist_or_nephrologist_or_neurologist_or_consult',
                prescriber_rems_enrolled=True, **BRANCHES[indication])


def test_all_indications_products_and_age_boundaries():
    for indication in BRANCHES:
        minimum = 1 / 12 if indication in ('ahus', 'pnh') else 18
        for product in ('soliris', 'ultomiris'):
            for age in (0, minimum - 0.00001, minimum, 18, 80):
                facts = dict(facts_for(indication), product=product, age_years=age)
                result = evaluate(pack(), facts)
                failures = set()
                if age < minimum:
                    failures.add('fda_labeled_age')
                if indication == 'nmosd' and product == 'ultomiris':
                    failures.add('product_allowed_for_indication')
                assert result.decision == ('fail' if failures else 'pass'), result
                assert {c['id'] for c in result.failed_clauses} == failures
                assert result.citations


def test_all_clinical_and_shared_gates_and_missing_facts():
    p = pack()
    for indication in BRANCHES:
        facts = facts_for(indication)
        assert evaluate(p, facts).decision == 'pass'
        for fact in facts:
            missing = facts.copy()
            del missing[fact]
            result = evaluate(p, missing)
            assert result.decision == 'need_info', (fact, result)
            assert result.missing_facts == [fact], (fact, result)
        for fact in set(facts) - {'indication', 'product', 'age_years'}:
            clause = next(c for c in p['criteria'] if c['id'] == fact)
            predicate = clause['predicate']
            for option in p['fact_ui'][fact]['options']:
                changed = _coerce_patient({fact: option['value']})
                result = evaluate(p, dict(facts, **changed))
                allowed = predicate.get('values', [predicate.get('value')])
                expected = 'pass' if changed[fact] in allowed else 'fail'
                assert result.decision == expected, (indication, fact, option, result)
                assert {c['id'] for c in result.failed_clauses} == ({fact} if expected == 'fail' else set())
        # Stale answers from other branches must not block the active branch.
        inactive = {key: 'invalid' for branch, values in BRANCHES.items()
                    if branch != indication for key in values}
        assert evaluate(p, dict(facts, **inactive)).decision == 'pass'


def test_closed_indication_and_product():
    for invalid in ('yes', 'no', 'unknown', 'other', True, False):
        for key, clause in [('indication', 'indication_fda_labeled'),
                            ('product', 'product_allowed_for_indication')]:
            result = evaluate(pack(), dict(facts_for('ahus'), **{key: invalid}))
            assert result.decision == 'fail'
            assert clause in {c['id'] for c in result.failed_clauses}


def test_ui_gating_and_age_band_coercion():
    p = pack()
    fields = {f['key']: f for f in drug_detail('soliris')['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert {o['value'] for o in fields['indication']['options']} == set(BRANCHES)
    for field in fields.values():
        assert field['type'] == 'select' and not field.get('free_text')
        assert field['options']
    for indication, branch in BRANCHES.items():
        for key in branch:
            clause = next(c for c in p['criteria'] if c['id'] == key)
            assert clause['when'] == fields[key]['when'] == {'fact': 'indication', 'eq': indication}
        for option in fields['age_years']['options']:
            facts = dict(facts_for(indication), **_coerce_patient({'age_years': option['value']}))
            minimum = 1 / 12 if indication in ('ahus', 'pnh') else 18
            assert evaluate(p, facts).decision == ('pass' if facts['age_years'] >= minimum else 'fail')
    assert fields['age_years']['option_style'] == 'age_bands'


def test_metadata_catalog_bundles_and_alternatives():
    p = pack()
    assert len(p['criteria']) == 20
    assert p['drug'] == dict(name='Soliris', generic_name='eculizumab', therapeutic_class='complement-inhibitor')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2022-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/vlzpfpiq/202209-soliris_ultomiris_criteria_2022v2.pdf'
    assert (ROOT / p['source']['criteria_pdf']).exists()
    assert 'inferred_required_facts' not in p and p['max_units'] is None
    notes = ' '.join(p['notes'])
    for text in ('ravulizumab-cwvz', '4 months', '12 months', '1200 mg', '3600 mg', 'J1300', 'J1303', 'manual review'):
        assert text in notes
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 106
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 92
    assert p['alternatives'] == ['empaveli', 'fabhalta']
    assert 'soliris' in catalog['empaveli']['alternatives']
    for slug in ('soliris', 'empaveli'):
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / 'rule_packs' / f'{slug}.json').read_bytes()
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 106 and status['encoding_text_only'] == 92
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'myqorzotm'
    for ext in ('json', 'md'):
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
