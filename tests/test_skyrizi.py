"""Skyrizi AK Medicaid: adult indication gates, steps, safety and catalog."""
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
PEERS = ['entyvio', 'stelara', 'tremfya', 'infliximab', 'zymfentra', 'bimzelx']
ACTIVITY = {
    'plaque_psoriasis': {'pasi_status': 'pasi_gte_12'},
    'psoriatic_arthritis': {'psa_clinical_activity': 'actively_inflamed_joints', 'haq_di_baseline': 'submitted'},
    'crohns_disease': {'cdai_status': 'cdai_gte_220'},
    'ulcerative_colitis': {'mms_status': 'mms_gte_5'},
}
SAFETY = ['no_active_clinically_significant_infection', 'not_receiving_phototherapy',
          'not_receiving_another_biologic']


def load_pack():
    return json.loads((BASE / 'skyrizi.json').read_text())


def facts_for(indication):
    return dict(indication=indication, age_years=18, tnf_blocker_failure='trial_failure',
                additional_prior_therapy='trial_failure_including_topical' if indication == 'plaque_psoriasis' else 'trial_failure',
                **dict.fromkeys(SAFETY, True), **ACTIVITY[indication])


def test_metadata_selects_and_gates():
    p = load_pack()
    assert p['drug'] == dict(name='Skyrizi', generic_name='risankizumab-rzaa', therapeutic_class='biologics')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'non_preferred'
    assert p['source']['effective_date'] == '2025-03-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/bm3hvtyo/skyrizi-criteria-2025.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/skyrizi-criteria-2025.pdf'
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 12
    fields = {f['key']: f for f in drug_detail('skyrizi')['fact_fields']}
    assert set(fields) == set(p['fact_ui']) == {f for c in p['criteria'] for f in c['required_facts']}
    assert not any('specialty' in k or 'latex' in k or 'hypersensitivity' in k for k in fields)
    assert [o['value'] for o in fields['indication']['options']] == list(ACTIVITY)
    assert p['fact_ui']['age_years']['option_style'] == 'age_bands'
    assert 'options' not in p['fact_ui']['age_years']
    assert [float(o['value']) for o in fields['age_years']['options']] == [0, .5, 1, 6, 12, 18]
    clauses = {c['id']: c for c in p['criteria']}
    gated = {key: {'fact': 'indication', 'in': [ind]} for ind, facts in ACTIVITY.items() for key in facts}
    for key, field in fields.items():
        assert field['type'] == 'select' and field['options'] and not field.get('free_text')
        assert field.get('when') == p['fact_ui'][key].get('when') == gated.get(key)
        assert clauses['fda_labeled_age' if key == 'age_years' else 'indication_fda_labeled' if key == 'indication' else key].get('when') == gated.get(key)
    assert p['max_units']['quantity'] is None and p['max_units']['days_supply'] is None
    for text in ['Version 1', '12/11/2024', '01/17/2025', '03/1/2025', 'specialty', 'monitoring plan',
                 'nature of failure', 'complete medication regimen', '3 months', '12 months', '150 mg',
                 '600 mg', '1200 mg', '180–360 mg', 'tuberculosis', 'alkaline phosphatase', 'bilirubin',
                 'Live vaccines', 'Humira', 'Hadlima', 'Rinvoq', 'manual review']:
        assert text in ' '.join(p['notes']), text


def test_paths_options_and_missing_facts():
    p = load_pack()
    for indication in ACTIVITY:
        facts = facts_for(indication)
        result = evaluate(p, facts)
        assert result.decision == 'pass' and not result.missing_facts
        raw = {k: 'yes' if v is True else str(v) for k, v in facts.items()}
        assert _coerce_patient(raw) == facts
        for key in facts:
            missing = dict(facts)
            del missing[key]
            result = evaluate(p, missing)
            assert result.decision == 'need_info' and result.missing_facts == [key], result
            if key in ['indication', 'age_years']:
                continue
            for option in p['fact_ui'][key]['options']:
                value = option['value']
                passes = value != 'none' if key == 'psa_clinical_activity' else value == raw[key]
                result = evaluate(p, _coerce_patient(dict(raw, **{key: value})))
                assert result.decision == ('pass' if passes else 'fail'), (indication, key, value, result)
                if not passes:
                    assert {c['id'] for c in result.failed_clauses} == {key}
        for age in [0, 6, 17, 17.99, 18, 80]:
            result = evaluate(p, dict(facts, age_years=age))
            assert result.decision == ('pass' if age >= 18 else 'fail')
        for invalid in ['yes', 'no', 'unknown', True, False, 'other']:
            result = evaluate(p, dict(facts, indication=invalid))
            assert result.decision == 'fail'
            assert 'indication_fda_labeled' in {c['id'] for c in result.failed_clauses}
        # Even failing stale values for other indications must be skipped.
        stale = {k: 'none' for ind, activity in ACTIVITY.items() if ind != indication for k in activity}
        assert evaluate(p, dict(facts, **stale)).decision == 'pass'
    result = evaluate(p, {})
    assert result.decision == 'need_info'
    assert set(result.missing_facts) == set(facts_for('plaque_psoriasis')) - {'pasi_status'}


def test_catalog_and_alternatives():
    catalog = load_rule_pack_catalog()
    p = load_pack()
    assert get_rule_pack('skyrizi') == ('skyrizi', p)
    assert (BASE / 'skyrizi.json').read_bytes() == (BASE / 'rule_packs/skyrizi.json').read_bytes()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 114
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 84
    assert p['alternatives'] == PEERS
    for peer in PEERS:
        assert 'skyrizi' in catalog[peer]['alternatives']
        assert catalog[peer]['encoding_status'] == 'partial'
        assert catalog[peer]['criteria']
        mirror = BASE / f'{peer}.json'
        if mirror.exists():
            assert json.loads(mirror.read_text()) == catalog[peer]
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 114 and status['encoding_text_only'] == 84
    assert 'skyrizi' in status['partial_slugs']
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'veozah'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('skyrizi tests ok')
