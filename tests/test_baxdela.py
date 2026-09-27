"""Baxdela: adult ABSSSI with independent culture and step alternatives."""
import gzip
import itertools
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
PACK = json.loads((BASE / 'rule_packs/baxdela.json').read_text())
CULTURE = ['culture_pathogen_listed', 'culture_not_feasible']
STEP = ['two_prior_antibiotics_including_fluoroquinolone',
        'ci_intolerance_all_other_absssi_antibiotics']


def facts():
    return dict(age_years=18, indication='absssi',
                culture_pathogen_listed=True,
                two_prior_antibiotics_including_fluoroquinolone=True)


@pytest.mark.parametrize('values', list(itertools.product([True, False, None], repeat=4)))
def test_independent_or_truth_tables(values):
    patient = dict(age_years=18, indication='absssi', **dict(zip(CULTURE + STEP, values)))
    def branch(vals):
        return 'pass' if True in vals else 'need_info' if None in vals else 'fail'
    outcomes = [branch(values[:2]), branch(values[2:])]
    # The shared engine prioritizes missing evidence across clauses.
    expected = 'need_info' if 'need_info' in outcomes else 'fail' if 'fail' in outcomes else 'pass'
    assert evaluate(PACK, patient).decision == expected


@pytest.mark.parametrize('culture,step', list(itertools.product(CULTURE, STEP)))
def test_paths_missing_and_ui(culture, step):
    patient = dict(age_years=18, indication='absssi', **{culture: True, step: True})
    assert evaluate(PACK, patient).decision == 'pass'
    for key in patient:
        for null in [False, True]:
            incomplete = dict(patient)
            if null:
                incomplete[key] = None
            else:
                del incomplete[key]
            result = evaluate(PACK, incomplete)
            assert result.decision == 'need_info'
            assert key in result.missing_facts
    form = {k: 'yes' if v is True else str(v) for k, v in patient.items()}
    assert evaluate(PACK, _coerce_patient(form)).decision == 'pass'
    assert evaluate(PACK, dict(patient, age_years=17.99)).decision == 'fail'
    assert evaluate(PACK, dict(patient, indication='other')).decision == 'fail'


def test_catalog_metadata_notes_and_ui():
    catalog = load_rule_pack_catalog()
    assert catalog['baxdela'] == PACK
    assert PACK['drug']['generic_name'] == 'delafloxacin'
    assert PACK['drug']['therapeutic_class'] == 'fluoroquinolone-antibiotic'
    assert PACK['source']['effective_date'] == '2019-03-11'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert evaluate(PACK, {}).decision == 'need_info'
    assert evaluate(PACK, facts()).citations == [PACK['source']['citation']]
    notes = ' '.join(PACK['notes'])
    for term in ['450mg', '14 days', '28 x', 'medical benefit', 'tendon rupture',
                 'peripheral neuropathy', 'CNS', 'myasthenia gravis', 'rash', 'manual review']:
        assert term in notes
    detail = drug_detail('baxdela')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(PACK['fact_ui'])
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert (BASE/'baxdela.json').read_bytes() == (BASE/'rule_packs/baxdela.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 164
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 34
    for folder in [BASE, BASE.parent]:
        status = json.loads((folder/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (164, 34)
        assert status['next_candidate'] == 'vimovo'
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status']=='partial')
    assert catalog['bone-resorption-inhibitors']['encoding_status'] == 'partial'
