"""Stelara AK Medicaid Version 4: indication branches, exclusions and catalog."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog
from ui.app import _coerce_patient

PEERS = ['entyvio', 'skyrizi', 'tremfya', 'infliximab', 'zymfentra', 'bimzelx']
PATHS = [('plaque_psoriasis', 6, 'trial_failure_including_topical', 'pasi_gte_12'),
         ('psoriatic_arthritis', 6, 'trial_failure', 'haq_di_gte_2'),
         ('crohns_disease', 18, 'trial_failure', 'cdai_baseline_submitted'),
         ('ulcerative_colitis', 18, 'trial_failure', 'mayo_baseline_submitted')]


def load_pack():
    return json.loads((ROOT / 'data/alaska/parsed/stelara.json').read_text())


def facts_for(path):
    indication, age, therapy, score = path
    return dict(indication=indication, age_years=age, tnf_blocker_failure='trial_failure',
                additional_prior_therapy=therapy, disease_activity_status=score,
                no_known_hypersensitivity_ustekinumab=True, no_active_severe_infection=True,
                not_concurrent_integrin_or_tnf=True, not_concurrent_phototherapy=True,
                latex_safe_for_device='no_latex_allergy')


def test_metadata_and_gaps():
    p = load_pack()
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'non_preferred'
    assert p['drug'] == dict(name='Stelara', generic_name='ustekinumab', therapeutic_class='biologics')
    assert p['source']['effective_date'] == '2024-11-01'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/cjkk4iyu/stelara_criteria.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/stelara_criteria.pdf'
    assert 'inferred_required_facts' not in p
    assert len(p['criteria']) == 10
    assert {f for c in p['criteria'] for f in c['required_facts']} == set(facts_for(PATHS[0]))
    assert p['max_units']['quantity'] is None and p['max_units']['days_supply'] is None
    for text in ['Version 4', '11/14/2014', '9/20/2024', '11/1/2024', 'specialty',
                 'monitoring plan', 'nature of failure', 'current weight', 'complete medication regimen',
                 '4 weeks', '12 months', '6 months', '45 mg', '90 mg', '100 kg', 'IV infusion',
                 'RPLS', 'live vaccines', 'UV', 'CYP450', 'Humira', 'Hadlima', 'Rinvoq', 'manual review']:
        assert text in ' '.join(p['notes']), text


def test_closed_selects_and_all_options():
    p = load_pack()
    fields = {f['key']: f for f in drug_detail('stelara')['fact_fields']}
    assert set(fields) == set(p['fact_ui']) == set(facts_for(PATHS[0]))
    assert not any('specialty' in f for f in fields)
    assert [o['value'] for o in fields['indication']['options']] == [r[0] for r in PATHS]
    assert p['fact_ui']['age_years']['option_style'] == 'age_bands'
    assert 'options' not in p['fact_ui']['age_years']
    assert [float(o['value']) for o in fields['age_years']['options']] == [0, .5, 1, 6, 12, 18]
    for f in fields.values():
        assert f['type'] == 'select' and f['options'] and not f.get('free_text')
    for invalid in ['yes', 'no', 'unknown', True, False, 'other']:
        result = evaluate(p, dict(facts_for(PATHS[0]), indication=invalid))
        assert result.decision == 'fail'
        assert 'indication_fda_labeled' in {c['id'] for c in result.failed_clauses}
    for path in PATHS:
        facts = facts_for(path)
        raw = {k: 'yes' if v is True else str(v) for k, v in facts.items()}
        assert _coerce_patient(raw) == facts
        for key, field in fields.items():
            if key == 'indication':
                continue  # Each complete indication path is checked below.
            for option in field['options']:
                value = option['value']
                if key == 'age_years':
                    passes = float(value) >= path[1]
                elif key == 'latex_safe_for_device':
                    passes = value in ['no_latex_allergy', 'using_vial_not_pfs']
                else:
                    passes = value == raw[key]
                result = evaluate(p, _coerce_patient(dict(raw, **{key: value})))
                assert result.decision == ('pass' if passes else 'fail'), (path, key, value, result)
                if not passes:
                    clause = 'fda_labeled_age_for_indication' if key == 'age_years' else key
                    assert {c['id'] for c in result.failed_clauses} == {clause}


def test_indication_age_boundaries_and_missing():
    p = load_pack()
    for path in PATHS:
        facts = facts_for(path)
        for age in [path[1], path[1] + 1, 80]:
            assert evaluate(p, dict(facts, age_years=age)).decision == 'pass'
        for age in [0, path[1] - .01]:
            result = evaluate(p, dict(facts, age_years=age))
            assert result.decision == 'fail'
            assert {c['id'] for c in result.failed_clauses} == {'fda_labeled_age_for_indication'}
        for key in facts:
            missing = dict(facts)
            del missing[key]
            result = evaluate(p, missing)
            assert result.decision == 'need_info' and result.missing_facts == [key], result
    result = evaluate(p, {})
    assert result.decision == 'need_info' and set(result.missing_facts) == set(facts)


def test_catalog_mirrors_status_and_alternatives():
    b = ROOT / 'data/alaska/parsed'
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('stelara') == ('stelara', load_pack())
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (b / 'rule_packs').glob('*.json')}
    assert json.loads((b / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(b / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert (b / 'stelara.json').read_bytes() == (b / 'rule_packs/stelara.json').read_bytes()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 126
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 72
    assert catalog['stelara']['alternatives'] == PEERS
    for peer in PEERS:
        assert 'stelara' in catalog[peer]['alternatives']
        assert catalog[peer]['encoding_status'] == 'partial'
        assert catalog[peer]['criteria']
        mirror = b / f'{peer}.json'
        if mirror.exists():
            assert json.loads(mirror.read_text()) == catalog[peer]
    status = json.loads((b / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 126 and status['encoding_text_only'] == 72
    assert 'stelara' in status['partial_slugs']
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for suffix in ['json', 'md']:
        assert (b / f'ENCODING_STATUS.{suffix}').read_bytes() == (b.parent / f'ENCODING_STATUS.{suffix}').read_bytes()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
    print('stelara tests ok')
