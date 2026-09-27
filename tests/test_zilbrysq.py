"""Alaska Zilbrysq eligibility, safety gates, UI and catalog regressions."""
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
TWO = 'inadequate_or_ci_two_or_more_is_agents_ge_12mo'
ONE = 'inadequate_or_ci_one_is_agent_plus_chronic_pe_plasmapheresis_or_ivig'


def pack():
    return json.loads((BASE / 'rule_packs/zilbrysq.json').read_text())


def facts():
    return dict(indication='generalized_myasthenia_gravis', age_years=18,
                prescriber_specialty='neurologist_or_consult', mgfa_class='ii_iii_or_iv',
                mg_antibody='achr_positive', mg_adl_score='gte_6',
                immunosuppressive_step=TWO,
                meningococcal_vaccine_acyw_and_b_ge_14d_prior='completed_or_current_ge_14d',
                prescriber_rems_enrolled='enrolled',
                no_active_meningococcal_infection='no_active_infection')


@pytest.mark.parametrize('step', [TWO, ONE])
def test_both_step_pathways(step):
    assert evaluate(pack(), dict(facts(), immunosuppressive_step=step)).decision == 'pass'


@pytest.mark.parametrize('key', list(facts()))
def test_missing_gates(key):
    patient = facts()
    del patient[key]
    result = evaluate(pack(), patient)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('key,value', [
    ('indication', 'other'), ('indication', True), ('indication', 'yes'),
    ('age_years', 17.999), ('prescriber_specialty', 'other'),
    ('mgfa_class', 'other'), ('mg_antibody', 'musk_positive'),
    ('mg_antibody', 'neither'), ('mg_adl_score', 'lt_6_or_not_documented'),
    ('mg_adl_score', 'gte_3'), ('immunosuppressive_step', 'none'),
    ('immunosuppressive_step', 'failed_two_or_more_is_12mo'),
    ('meningococcal_vaccine_acyw_and_b_ge_14d_prior', 'not_met'),
    ('prescriber_rems_enrolled', 'not_enrolled'),
    ('no_active_meningococcal_infection', 'active_infection'),
])
def test_failed_gates(key, value):
    result = evaluate(pack(), dict(facts(), **{key: value}))
    assert result.decision == 'fail' and len(result.failed_clauses) == 1
    assert result.failed_clauses[0]['id'] == {'indication': 'indication_fda_labeled', 'age_years': 'minimum_age'}.get(key, key)
    assert result.citations


def test_ui_closed_options_and_age_boundary():
    p = pack()
    fields = {f['key']: f for f in drug_detail('zilbrysq')['fact_fields']}
    assert set(fields) == set(facts())
    assert [o['value'] for o in fields['indication']['options']] == ['generalized_myasthenia_gravis']
    assert [o['value'] for o in fields['immunosuppressive_step']['options']] == [TWO, ONE, 'none']
    for key, field in fields.items():
        assert field['type'] == 'select' and field['options'] and not field.get('free_text')
        for option in field['options']:
            patient = dict(facts(), **_coerce_patient({key: option['value']}))
            expected = patient[key] == facts()[key] or (key == 'immunosuppressive_step' and patient[key] == ONE)
            assert evaluate(p, patient).decision == ('pass' if expected else 'fail')
    assert all('when' not in c for c in p['criteria'])


def test_catalog_mirrors_notes_and_alternatives():
    p = pack()
    assert p['drug'] == dict(name='Zilbrysq', generic_name='zilucoplan', therapeutic_class='complement-inhibitor')
    assert p['source']['effective_date'] == '2024-03-01'
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert len(p['criteria']) == 10 and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert 'rystiggo' in p['alternatives'] and 'zilbrysq' in catalog['rystiggo']['alternatives']
    for slug in ['zilbrysq', 'rystiggo']:
        assert (BASE / f'{slug}.json').read_bytes() == (BASE / 'rule_packs' / f'{slug}.json').read_bytes()
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 81
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 117
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['encoding_partial'] == 81 and status['encoding_text_only'] == 117
    assert status['next_candidate'] == 'myalept'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for ext in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()
    notes = ' '.join(p['notes'])
    for text in ['Version 1', '12/21/2023', '01/19/2024', '03/01/2024', '3 months', '12 months',
                 'positive clinical response', 'tolerability', 'meningococcal', 'Pancreatitis',
                 'pancreatic cysts', 'fetal harm', '32.4 mg', '30 prefilled syringes per 30 days', 'manual review']:
        assert text in notes
