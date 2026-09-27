"""Entyvio Alaska Medicaid Version 2.1 initial eligibility and catalog integration."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog
from ui.app import _coerce_patient

PEERS = ['skyrizi', 'stelara', 'infliximab', 'tremfya', 'zymfentra']


def load_pack():
    return json.loads((ROOT / 'data/alaska/parsed/entyvio.json').read_text())


def _base(**extra):
    facts = dict(indication='ulcerative_colitis', age_years=18.0,
                 conventional_therapy_60d='trial_failure_60d',
                 tnf_blocker_60d='trial_failure_60d', cdai_status='not_applicable_uc',
                 no_known_hypersensitivity_vedolizumab=True,
                 no_active_severe_infection=True, not_concurrent_integrin_or_tnf=True)
    return dict(facts, **extra)


def _assert_fail(clause, **extra):
    result = evaluate(load_pack(), _base(**extra))
    assert result.decision == 'fail', result
    assert {c['id'] for c in result.failed_clauses} == {clause}, result
    assert result.citations


def test_metadata_and_gaps():
    pack = load_pack()
    assert pack['encoding_status'] == 'partial'
    assert pack['pdl_status'] == 'non_preferred'
    assert pack['drug'] == dict(name='Entyvio', generic_name='vedolizumab', therapeutic_class='biologics')
    assert pack['source']['effective_date'] == '2024-01-01'
    assert pack['source']['citation'] == 'https://health.alaska.gov/media/lk2pxysn/entyvio_criteria_20231117update.pdf'
    assert pack['source']['criteria_pdf'] == 'data/alaska/raw/entyvio_criteria_20231117update.pdf'
    assert 'inferred_required_facts' not in pack
    assert len(pack['criteria']) == 8
    assert {f for c in pack['criteria'] for f in c['required_facts']} == set(_base())
    assert pack['max_units']['quantity'] == 300
    assert pack['max_units']['days_supply'] is None
    notes = ' '.join(pack['notes'])
    for text in ['Version 2.1', '11/14/2014', '11/17/2023', '01/1/2024', '> 18', '< 18',
                 'specialty', 'PML', 'hepatic', 'nature of failure', 'week 14', 'taper',
                 'AST/ALT > 20', 'bilirubin > 10', 'life-threatening diarrhea', '12 months',
                 '216 mg', 'J3380', 'Live vaccines', 'manual review', 'Humira', 'Hadlima', 'Rinvoq']:
        assert text in notes, text


def test_closed_selects_and_ui_coercion():
    fields = {f['key']: f for f in drug_detail('entyvio')['fact_fields']}
    assert set(fields) == set(_base()) == set(load_pack()['fact_ui'])
    assert not any('specialty' in key for key in fields)
    for field in fields.values():
        assert field['type'] == 'select' and field['option_source'] == 'fact_ui'
        assert field.get('free_text') is not True and field['options']
    assert fields['indication']['options'] == [
        {'value': 'ulcerative_colitis', 'label': 'Moderately to severely active ulcerative colitis (UC)'},
        {'value': 'crohns_disease', 'label': 'Moderately to severely active Crohn’s disease (CD)'}]
    assert fields['age_years']['options'] == [
        {'value': '0', 'label': 'Under 18'}, {'value': '18', 'label': '18+'}]
    for invalid in ['yes', 'no', 'unknown', True, False, 'other']:
        result = evaluate(load_pack(), _base(indication=invalid))
        assert result.decision == 'fail'
        assert 'indication_fda_labeled' in {c['id'] for c in result.failed_clauses}
    for indication, cdai in [('ulcerative_colitis', 'not_applicable_uc'), ('crohns_disease', 'gt_220')]:
        raw = {k: 'yes' if v is True else str(v) for k, v in _base(indication=indication, cdai_status=cdai).items()}
        raw['age_years'] = '18'
        assert _coerce_patient(raw) == _base(indication=indication, cdai_status=cdai)
        for fact, field in fields.items():
            for option in field['options']:
                value = option['value']
                passing = {'indication': indication, 'cdai_status': cdai, 'age_years': '18',
                           'conventional_therapy_60d': 'trial_failure_60d', 'tnf_blocker_60d': 'trial_failure_60d'}
                result = evaluate(load_pack(), _coerce_patient(dict(raw, **{fact: value})))
                assert result.decision == ('pass' if value == passing.get(fact, 'yes') else 'fail'), (fact, value, result)


def test_age_steps_cdai_and_safety():
    for age in [18, 19, 80]:
        assert evaluate(load_pack(), _base(age_years=age)).decision == 'pass'
    for age in [0, 17, 17.99]:
        _assert_fail('minimum_age', age_years=age)
    for fact in ['conventional_therapy_60d', 'tnf_blocker_60d']:
        _assert_fail(fact, **{fact: 'none'})
    for indication, accepted in [('ulcerative_colitis', 'not_applicable_uc'), ('crohns_disease', 'gt_220')]:
        for cdai in ['gt_220', '151_to_220', 'lte_150', 'not_applicable_uc']:
            if cdai == accepted:
                assert evaluate(load_pack(), _base(indication=indication, cdai_status=cdai)).decision == 'pass'
            else:
                _assert_fail('cdai_status', indication=indication, cdai_status=cdai)
    for fact, value in _base().items():
        if value is True:
            _assert_fail(fact, **{fact: False})


def test_missing_facts_need_info():
    for indication, cdai in [('ulcerative_colitis', 'not_applicable_uc'), ('crohns_disease', 'gt_220')]:
        for fact in _base():
            facts = _base(indication=indication, cdai_status=cdai)
            del facts[fact]
            result = evaluate(load_pack(), facts)
            assert result.decision == 'need_info', result
            assert result.missing_facts == [fact], result
    result = evaluate(load_pack(), {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(_base())


def test_catalog_mirrors_status_and_bidirectional_alternatives():
    base = ROOT / 'data/alaska/parsed'
    pack = load_pack()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('entyvio') == ('entyvio', pack)
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (base / 'rule_packs').glob('*.json')}
    assert json.loads((base / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(base / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (base / 'entyvio.json').read_bytes() == (base / 'rule_packs/entyvio.json').read_bytes()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 26
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 172
    assert pack['alternatives'] == PEERS
    for peer in PEERS:
        assert catalog[peer]['encoding_status'] == 'partial'
        assert catalog[peer]['criteria']
        assert 'entyvio' in catalog[peer]['alternatives']
        mirror = base / f'{peer}.json'
        if mirror.exists():
            assert 'entyvio' in json.loads(mirror.read_text())['alternatives']
    status = json.loads((base / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 26 and status['encoding_text_only'] == 172
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    assert 'entyvio' in status['partial_slugs']
    for suffix in ['json', 'md']:
        assert (base / f'ENCODING_STATUS.{suffix}').read_bytes() == (base.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('entyvio tests ok')
