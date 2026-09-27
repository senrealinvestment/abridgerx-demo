"""Evenity: closed diagnosis, therapy alternatives, safety and lifetime doses."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
FACTS = dict(
    indication='postmenopausal_osteoporosis_high_fracture_risk',
    patient_population='postmenopausal_woman',
    osteoporosis_diagnosis='tscore_lte_minus_2_5',
    administered_by_healthcare_provider=True,
    oral_bisphosphonate_step='trial_oral_bp_1yr_suboptimal',
    injectable_osteo_step='trial_failure_or_intolerant',
    calcium_vitd_counseling_done=True,
    no_mi_or_stroke_preceding_year=True,
    no_hypocalcemia=True,
    lifetime_monthly_doses_lt_12='doses_received_lt_12',
)


def pack():
    return json.loads((BASE / 'evenity.json').read_text())


def test_metadata_and_closed_indication():
    p = pack()
    assert p['drug'] == dict(name='Evenity', generic_name='romosozumab-aqqg', therapeutic_class='metabolic')
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert p['source']['effective_date'] == '2020-03-16'
    assert p['source']['citation'] == 'https://health.alaska.gov/media/lisiaj4z/202001_evenity_criteria_2019.pdf'
    assert p['source']['criteria_pdf'] == 'data/alaska/raw/202001_evenity_criteria_2019.pdf'
    assert len(p['criteria']) == 10 and 'inferred_required_facts' not in p
    assert p['alternatives'] == ['prolia']
    assert p['max_units']['quantity'] is None and p['max_units']['days_supply'] is None
    assert [o['value'] for o in p['fact_ui']['indication']['options']] == [FACTS['indication']]
    for invalid in ['yes', 'no', 'unknown', True, False, 'other']:
        r = evaluate(p, dict(FACTS, indication=invalid))
        assert r.decision == 'fail'
        assert [c['id'] for c in r.failed_clauses] == ['indication_fda_labeled']
    for text in ['Version 1', '12/10/2019', '1/17/2020', '3/16/2020', '3 months', '9 months', '12 monthly doses', '2×105 mg', '210 mg', 'MACE', 'ONJ', 'Hypersensitivity']:
        assert text in ' '.join(p['notes'])


@pytest.mark.parametrize('diagnosis', ['tscore_lte_minus_2_5', 'low_trauma_fracture_high_risk'])
@pytest.mark.parametrize('oral', ['trial_oral_bp_1yr_suboptimal', 'ci_to_oral_bp', 'unable_remain_upright_30min', 'intolerant_two_bp_manufacturers'])
def test_diagnosis_and_oral_bp_options(diagnosis, oral):
    assert evaluate(pack(), dict(FACTS, osteoporosis_diagnosis=diagnosis, oral_bisphosphonate_step=oral)).decision == 'pass'


@pytest.mark.parametrize('key,value', [
    ('patient_population', 'not_postmenopausal_woman'),
    ('osteoporosis_diagnosis', 'none'),
    ('oral_bisphosphonate_step', 'none'),
    ('injectable_osteo_step', 'none'),
    ('administered_by_healthcare_provider', False),
    ('calcium_vitd_counseling_done', False),
    ('no_mi_or_stroke_preceding_year', False),
    ('no_hypocalcemia', False),
    ('lifetime_monthly_doses_lt_12', 'doses_received_gte_12'),
])
def test_denials(key, value):
    r = evaluate(pack(), dict(FACTS, **{key: value}))
    assert r.decision == 'fail'
    assert [c['id'] for c in r.failed_clauses] == [key]


def test_missing_facts_and_ui():
    p = pack()
    assert evaluate(p, FACTS).decision == 'pass'
    assert set(evaluate(p, {}).missing_facts) == set(FACTS)
    for key in FACTS:
        facts = dict(FACTS)
        del facts[key]
        r = evaluate(p, facts)
        assert r.decision == 'need_info' and r.missing_facts == [key]
    fields = {f['key']: f for f in drug_detail('evenity')['fact_fields']}
    assert set(fields) == set(FACTS)
    assert all(f['type'] == 'select' and f['options'] and not f.get('free_text') for f in fields.values())
    submitted = {k: 'yes' if v is True else v for k, v in FACTS.items()}
    assert evaluate(p, _coerce_patient(submitted)).decision == 'pass'
    for key, value in FACTS.items():
        if value is True:
            assert evaluate(p, _coerce_patient(dict(submitted, **{key: 'no'}))).decision == 'fail'


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 117
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 81
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as f:
        assert json.load(f) == catalog
    assert (BASE / 'evenity.json').read_bytes() == (BASE / 'rule_packs/evenity.json').read_bytes()
    assert catalog['prolia']['encoding_status'] == 'partial'
    assert catalog['actiq']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 117 and status['encoding_text_only'] == 81
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    assert status['next_candidate'] == 'rhapsido'
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
    assert 'Biologics batch exhausted:' in (BASE / 'ENCODING_STATUS.md').read_text()
