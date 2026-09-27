"""Leqvio source-specific branches, therapy exceptions, and catalog integrity."""
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
H = 'heterozygous_familial_hypercholesterolemia'
A = 'clinical_ascvd'


def pack():
    return json.loads((BASE / 'rule_packs/leqvio.json').read_text())


def facts(indication):
    f = dict(indication=indication, age_years=18, prescriber_specialty='cardiology',
             current_ldl_labs_submitted_within_12_months=True,
             statin_step='two_high_potency_statins_max_tolerated_12wk_each_one_with_ezetimibe_failed',
             pcsk9_step='failed_ldl_goal_12wk_with_or_without_statin',
             healthcare_professional_administration=True, not_concurrent_pcsk9_inhibitor=True)
    if indication == H:
        f.update(baseline_ldl_ge_190_before_lipid_therapy=True,
                 hefh_confirmation='first_degree_mi_under_60', hefh_ldl_goal_not_achieved=True)
    else:
        f.update(ascvd_confirmation='acute_coronary_syndromes', ascvd_ldl_goal_not_achieved=True)
    return f


def test_every_option_missing_fact_and_branch_isolation():
    p = pack()
    for indication in (H, A):
        base = facts(indication)
        assert evaluate(p, base).decision == 'pass'
        for key in base:
            missing = base.copy()
            del missing[key]
            result = evaluate(p, missing)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
            if key == 'indication':
                continue
            clause = next(c for c in p['criteria'] if c['id'] == key)
            pred = clause['predicate']
            for option in p['fact_ui'][key]['options']:
                value = _coerce_patient({key: option['value']})[key]
                allowed = (value >= 18 if key == 'age_years' else
                           value in pred['values'] if pred['op'] == 'in' else value == pred['value'])
                result = evaluate(p, dict(base, **{key: value}))
                assert result.decision == ('pass' if allowed else 'fail'), (key, value, result)
                assert {c['id'] for c in result.failed_clauses} == (set() if allowed else {key})
                assert result.citations == [p['source']['citation']]
        opposite = facts(A if indication == H else H)
        inactive = {k: 'not_met' for k in opposite.keys() - base.keys()}
        assert evaluate(p, dict(base, **inactive)).decision == 'pass'
        for age in (0, 17.99, 18, 80):
            assert evaluate(p, dict(base, age_years=age)).decision == ('pass' if age >= 18 else 'fail')
        for invalid in ('unknown', 'other', True, False, 'homozygous_familial_hypercholesterolemia'):
            assert evaluate(p, dict(base, indication=invalid)).decision == 'fail'
        assert evaluate(p, dict(base, pcsk9_step='intolerant')).decision == 'fail'


def test_ui_confirmation_lists_and_metadata():
    p = pack()
    fields = {f['key']: f for f in drug_detail('leqvio')['fact_fields']}
    assert set(fields) == set(p['fact_ui']) == set(facts(H)) | set(facts(A))
    assert [o['value'] for o in fields['indication']['options']] == [H, A]
    assert len(p['criteria']) == 13
    assert len(next(c for c in p['criteria'] if c['id'] == 'hefh_confirmation')['predicate']['values']) == 9
    assert len(next(c for c in p['criteria'] if c['id'] == 'ascvd_confirmation')['predicate']['values']) == 6
    for c in p['criteria']:
        field = fields[c['id']]
        assert field['type'] == 'select' and not field.get('free_text')
        assert c.get('when') == p['fact_ui'][c['id']].get('when')
        assert c['citation'] == p['source']['citation']
    assert p['drug'] == dict(name='Leqvio', generic_name='inclisiran', therapeutic_class='pcsk9-sirna')
    assert p['source']['effective_date'] == '2023-01-02'
    assert p['encoding_status'] == 'partial' and p['max_units'] is None
    assert p['alternatives'] == ['praluent']
    assert 'inferred_required_facts' not in p
    for phrase in ('6 months', '12 months', '10%', '284 mg', '3 months', 'J1306',
                   'arthralgia', 'dyspnea', 'upper arm', 'manual review'):
        assert phrase in ' '.join(p['notes'])


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 131
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 67
    assert catalog['opsumit']['encoding_status'] == 'partial'
    assert catalog['praluent']['alternatives'] == ['leqvio']
    for slug in ('leqvio', 'praluent'):
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / f'rule_packs/{slug}.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (131, 67)
    assert status['next_candidate'] == 'imbruvica'
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for ext in ('json', 'md'):
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()
