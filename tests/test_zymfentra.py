"""Zymfentra AK Medicaid: SC maintenance eligibility, safety and catalog."""
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
PEERS = ['entyvio', 'stelara', 'skyrizi', 'tremfya', 'infliximab']
INDICATIONS = ['ulcerative_colitis', 'crohns_disease']
ATTESTATIONS = ['not_concurrent_another_biologic', 'tb_and_hbv_screened',
                'no_clinically_significant_infection', 'no_history_of_malignancy',
                'no_history_moderate_severe_copd', 'no_history_of_chf']


def load_pack():
    return json.loads((BASE / 'zymfentra.json').read_text())


def facts_for(indication):
    return dict(indication=indication, age_years=18,
                prescriber_specialty='gastroenterologist',
                iv_infliximab_prior_therapy='ge_10w_positive_response',
                **dict.fromkeys(ATTESTATIONS, True))


def test_metadata_and_selects():
    p = load_pack()
    assert p['drug'] == dict(name='Zymfentra', generic_name='infliximab-dyyb', therapeutic_class='biologics')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'non_preferred'
    assert p['source']['effective_date'] == '2025-06-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/qpdj1blx/zymfentra_criteria_2025.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/zymfentra_criteria_2025.pdf'
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 10
    fields = {f['key']: f for f in drug_detail('zymfentra')['fact_fields']}
    assert set(fields) == set(p['fact_ui']) == set(facts_for(INDICATIONS[0]))
    assert set(fields) == {f for c in p['criteria'] for f in c['required_facts']}
    for field in fields.values():
        assert field['type'] == 'select' and field['options'] and not field.get('free_text')
    assert [o['value'] for o in fields['indication']['options']] == INDICATIONS
    for option in fields['indication']['options']:
        assert 'Moderately to severely active' in option['label']
        assert 'intravenously' in option['label']
    assert p['fact_ui']['age_years']['option_style'] == 'age_bands'
    assert 'options' not in p['fact_ui']['age_years']
    assert [float(o['value']) for o in fields['age_years']['options']] == [0, .5, 1, 6, 12, 18]
    assert [o['value'] for o in fields['prescriber_specialty']['options']] == ['gastroenterologist', 'primary_care', 'other']
    assert [o['value'] for o in fields['iv_infliximab_prior_therapy']['options']] == ['ge_10w_positive_response', 'ge_10w_no_response', 'lt_10w', 'none']
    for key in ATTESTATIONS:
        assert fields[key]['options'] == [{'value': 'yes', 'label': 'Yes'}, {'value': 'no', 'label': 'No'}]
    clauses = {c['id']: c['predicate'] for c in p['criteria']}
    assert clauses['fda_labeled_age'] == dict(op='gte', fact='age_years', value=18)
    assert clauses['prescriber_specialty'] == dict(op='in', fact='prescriber_specialty', values=['gastroenterologist'])
    assert clauses['iv_infliximab_prior_therapy'] == dict(op='eq', fact='iv_infliximab_prior_therapy', value='ge_10w_positive_response')
    assert p['max_units']['quantity'] == 2 and p['max_units']['days_supply'] == 28
    for text in ['Version 1', '03/12/2025', '04/18/2025', '06/01/2025', '12 months',
                 'initial/reauthorization', '120 mg every 14 days', '2 prefilled',
                 'lymphoma', '3 to 4 months', 'severe infection', 'live vaccines',
                 'manual review', 'IV Infliximab', 'partial']:
        assert text in ' '.join(p['notes']), text


def test_pass_fail_options_and_missing():
    p = load_pack()
    for indication in INDICATIONS:
        facts = facts_for(indication)
        assert evaluate(p, facts).decision == 'pass'
        raw = {k: 'yes' if v is True else str(v) for k, v in facts.items()}
        assert _coerce_patient(raw) == facts
        for key in facts:
            missing = dict(facts)
            del missing[key]
            result = evaluate(p, missing)
            assert result.decision == 'need_info' and result.missing_facts == [key]
            if key in ['indication', 'age_years']:
                continue
            for option in p['fact_ui'][key]['options']:
                value = option['value']
                result = evaluate(p, _coerce_patient(dict(raw, **{key: value})))
                assert result.decision == ('pass' if value == raw[key] else 'fail'), (key, value, result)
                if value != raw[key]:
                    assert {c['id'] for c in result.failed_clauses} == {key}
        for age in [0, 6, 17, 17.99, 18, 80]:
            result = evaluate(p, dict(facts, age_years=age))
            assert result.decision == ('pass' if age >= 18 else 'fail')
        for invalid in ['yes', 'no', 'unknown', True, False, 'other', 'plaque_psoriasis', 'psoriatic_arthritis']:
            result = evaluate(p, dict(facts, indication=invalid))
            assert result.decision == 'fail'
            assert {c['id'] for c in result.failed_clauses} == {'indication_fda_labeled'}
    result = evaluate(p, {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(facts_for(INDICATIONS[0]))


def test_catalog_and_alternatives():
    catalog = load_rule_pack_catalog()
    p = load_pack()
    assert get_rule_pack('zymfentra') == ('zymfentra', p)
    assert (BASE / 'zymfentra.json').read_bytes() == (BASE / 'rule_packs/zymfentra.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 150
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 48
    assert p['alternatives'] == PEERS
    for peer in PEERS:
        assert 'zymfentra' in catalog[peer]['alternatives']
        assert catalog[peer]['encoding_status'] == 'partial'
        assert catalog[peer]['criteria']
        mirror = BASE / f'{peer}.json'
        if mirror.exists():
            assert json.loads(mirror.read_text()) == catalog[peer]
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 150 and status['encoding_text_only'] == 48
    assert 'zymfentra' in status['partial_slugs']
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'leuprolide'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('zymfentra tests ok')
