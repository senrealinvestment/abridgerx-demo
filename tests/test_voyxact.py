"""Alaska Voyxact closed gates, exceptions, notes and catalog mirrors."""
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
PACK = json.loads((BASE / 'rule_packs/voyxact.json').read_text())
FACTS = dict(indication='primary_igan_at_risk_for_progression', age='at_least_18',
             prescriber_specialty='nephrologist', kidney_biopsy='confirmed',
             egfr='at_least_30', proteinuria_or_upcr='proteinuria_at_least_0_5',
             acei_arb_therapy='acei_max_tolerated_at_least_90_days_continue',
             systemic_immunosuppressant='absent', significant_active_infection='absent')


@pytest.mark.parametrize('clause', PACK['criteria'])
def test_closed_gates(clause):
    key = clause['id']
    for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['yes', 'no', 'unknown', True, False]:
        result = evaluate(PACK, dict(FACTS, **{key: value}))
        allowed = value in clause['predicate']['values']
        assert result.decision == ('pass' if allowed else 'fail')
        assert [c['id'] for c in result.failed_clauses] == ([] if allowed else [key])
        assert result.citations


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [True, False])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert key in result.missing_facts


@pytest.mark.parametrize('therapy', [
    'acei_max_tolerated_at_least_90_days_continue',
    'arb_max_tolerated_at_least_90_days_continue',
    'documented_ci_or_adverse_reaction_to_both'])
@pytest.mark.parametrize('lab', ['proteinuria_at_least_0_5', 'upcr_at_least_0_75', 'both'])
def test_alternative_routes_and_independent_denials(therapy, lab):
    facts = dict(FACTS, acei_arb_therapy=therapy, proteinuria_or_upcr=lab)
    assert evaluate(PACK, facts).decision == 'pass'
    for key in ['systemic_immunosuppressant', 'significant_active_infection']:
        result = evaluate(PACK, dict(facts, **{key: 'present'}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [key]


def test_ui_metadata_and_notes():
    detail = drug_detail('voyxact')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert len(fields['indication']['options']) == 1
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert evaluate(PACK, _coerce_patient(FACTS)).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'sibeprenlimab-szsi'
    assert PACK['drug']['therapeutic_class'] == 'april-blocker'
    assert PACK['source']['effective_date'] == '2026-06-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['Accelerated approval', 'proteinuria reduction', 'kidney function decline',
                 'confirmatory clinical trial', 'infection risk', '30 days', 'during therapy',
                 'upper respiratory tract infection', 'injection site erythema',
                 '6 months', '12 months', 'one 400mg/2ml syringe every 28 days', 'manual review']:
        assert text in ' '.join(PACK['notes'])



def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['voyxact'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'voyxact.json').read_bytes() == (BASE / 'rule_packs/voyxact.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 120
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 78
    assert catalog['xyrem']['encoding_status'] == 'text_only'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (120, 78)
        assert status['next_candidate'] == 'xyrem'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
