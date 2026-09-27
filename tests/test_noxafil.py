"""Noxafil oral suspension: independent indication branches and catalog integration."""
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
PACK = json.loads((BASE / 'rule_packs/noxafil.json').read_text())
PATHS = [
    dict(indication='prophylaxis_aspergillus_candida', age_years=13, hsct_gvhd=True),
    dict(indication='prophylaxis_aspergillus_candida', age_years=13,
         hematologic_malignancy_prolonged_neutropenia=True),
    dict(indication='opc', fungal_culture_labs_submitted=True),
    dict(indication='ropc', prior_azole_regimens_documented=True),
]


@pytest.mark.parametrize('facts', PATHS)
def test_paths_missing_null_and_ui(facts):
    assert evaluate(PACK, facts).decision == 'pass'
    for key in facts:
        for null in [False, True]:
            incomplete = dict(facts)
            if null:
                incomplete[key] = None
            else:
                del incomplete[key]
            result = evaluate(PACK, incomplete)
            assert result.decision == 'need_info'
            assert key in result.missing_facts
    form = {k: ('yes' if v else 'no') if isinstance(v, bool) else str(v)
            for k, v in facts.items()}
    assert evaluate(PACK, _coerce_patient(form)).decision == 'pass'
    assert evaluate(PACK, dict(facts, indication='other')).decision == 'fail'


@pytest.mark.parametrize('facts', [
    dict(PATHS[0], age_years=12.99),
    dict(PATHS[0], hsct_gvhd=False, hematologic_malignancy_prolonged_neutropenia=False),
    dict(PATHS[2], fungal_culture_labs_submitted=False),
    dict(PATHS[3], prior_azole_regimens_documented=False),
])
def test_denials(facts):
    assert evaluate(PACK, facts).decision == 'fail'


@pytest.mark.parametrize('facts', PATHS)
def test_indication_isolation(facts):
    irrelevant = dict(age_years=1, hsct_gvhd=False,
                      hematologic_malignancy_prolonged_neutropenia=False,
                      fungal_culture_labs_submitted=False,
                      prior_azole_regimens_documented=False)
    irrelevant.update(facts)
    assert evaluate(PACK, irrelevant).decision == 'pass'


def test_risk_unknown_is_not_denied():
    facts = dict(PATHS[0], hsct_gvhd=False)
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == ['hematologic_malignancy_prolonged_neutropenia']


def test_catalog_metadata_and_notes():
    catalog = load_rule_pack_catalog()
    assert catalog['noxafil'] == PACK
    assert PACK['drug']['generic_name'] == 'posaconazole'
    assert PACK['drug']['therapeutic_class'] == 'triazole-antifungal'
    assert PACK['source']['effective_date'] == '2022-06-01'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert evaluate(PACK, {}).decision == 'need_info'
    assert evaluate(PACK, PATHS[0]).citations == [PACK['source']['citation']]
    notes = ' '.join(PACK['notes'])
    for term in ['40 mg/mL', '105 mL', '3 months', 'clinical improvement',
                 'medical rationale', '14-day supply', '3/26/2013', '4/19/2013',
                 'neutronpenia', 'refactory', 'manual review']:
        assert term in notes
    detail = drug_detail('noxafil')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    for key, field in PACK['fact_ui'].items():
        assert fields[key]['type'] == 'select'
        assert not fields[key].get('free_text')
        if key != 'indication':
            assert fields[key]['when'] == field['when']
    assert (BASE/'noxafil.json').read_bytes() == (BASE/'rule_packs/noxafil.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 158
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 40
    for folder in [BASE, BASE.parent]:
        status = json.loads((folder/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (158, 40)
        assert status['next_candidate'] == 'quinine'
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status']=='partial')
    assert catalog['bone-resorption-inhibitors']['encoding_status'] == 'partial'
