"""ER/LA class PA paths, source scope, UI gates and catalog integrity."""
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
KINDS = ['nonpreferred_er_la_product_selection', 'quantity_limit_exception',
         'therapeutic_duplication_exception']
COMMON = ['full_medication_list_included', 'med_mme_calculated_and_documented', 'opioid_tolerant']
PRODUCT = ['letter_of_medical_necessity_around_the_clock', 'opioid_agreement_on_file',
           'preferred_er_la_trial_failed_or_rationale']


def pack():
    return json.loads((BASE / 'rule_packs/extended-release.json').read_text())


def facts(kind):
    return dict(indication=kind, **{k: True for k in COMMON + (PRODUCT if kind == KINDS[0] else [])})


@pytest.mark.parametrize('kind', KINDS)
def test_required_facts(kind):
    patient = facts(kind)
    assert evaluate(pack(), patient).decision == 'pass'
    for key, value in patient.items():
        missing = dict(patient)
        del missing[key]
        result = evaluate(pack(), missing)
        assert result.decision == 'need_info'
        assert key in result.missing_facts
        assert evaluate(pack(), dict(patient, **{key: False if value is True else 'unsupported'})).decision == 'fail'


@pytest.mark.parametrize('value', ['yes', 'no', True, False, 'unknown', 'chronic_pain', 'preferred_product_selection'])
def test_closed_request_type(value):
    assert evaluate(pack(), dict(facts(KINDS[0]), indication=value)).decision == 'fail'


@pytest.mark.parametrize('kind', KINDS[1:])
def test_exception_paths_ignore_product_selection_requirements(kind):
    assert evaluate(pack(), facts(kind)).decision == 'pass'
    assert evaluate(pack(), dict(facts(kind), **{k: False for k in PRODUCT})).decision == 'pass'
    assert not set(PRODUCT) & set(evaluate(pack(), {'indication': kind}).missing_facts)


def test_empty_and_notes_only():
    assert evaluate(pack(), {}).decision == 'need_info'
    assert set(pack()['fact_ui']) == {'indication', *COMMON, *PRODUCT}
    assert len(pack()['criteria']) == 7
    notes = ' '.join(pack()['notes'])
    for text in ['3/18/2016', '3/25/2016', '6 months', 'May 1, 2015', 'last day',
                 'lost, stolen or destroyed', 'travel or vacation', 'PDMP', 'REMS',
                 '100 mg', '50 MED', '12/12.5/25/50/75/100', 'Butrans', 'maxunitsall.pdf']:
        assert text in notes
    assert 'within the past year' in pack()['fact_ui'][PRODUCT[-1]]['label']
    assert 'OR documented medical rationale' in pack()['fact_ui'][PRODUCT[-1]]['label']


def test_ui_gating_and_coercion():
    p = pack()
    detail = drug_detail('extended-release')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    assert [o['value'] for o in fields['indication']['options']] == KINDS
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        assert field['options'] == p['fact_ui'][key]['options']
        assert field.get('when') == p['fact_ui'][key].get('when')
    for key in COMMON + PRODUCT:
        gate = {'fact': 'indication', 'in': KINDS} if key in COMMON else {'fact': 'indication', 'eq': KINDS[0]}
        assert fields[key]['when'] == gate
        assert next(c for c in p['criteria'] if c['id'] == key)['when'] == gate
    for kind in KINDS:
        patient = {k: 'yes' if v is True else v for k, v in facts(kind).items()}
        assert evaluate(p, _coerce_patient(patient)).decision == 'pass'
        patient['opioid_tolerant'] = 'no'
        assert evaluate(p, _coerce_patient(patient)).decision == 'fail'


def test_metadata_catalog_and_companion():
    p = pack()
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2016-03-25'
    assert 'inferred_required_facts' not in p
    assert p['alternatives'] == [] and p['max_units'] is None
    assert (BASE / 'extended-release.json').read_bytes() == (BASE / 'rule_packs/extended-release.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 198
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 0
    companion = catalog['long-acting-opioid-analgesics']
    assert companion['encoding_status'] == 'partial'
    assert companion['criteria'] == p['criteria']
    assert companion['fact_ui'] == p['fact_ui']
    assert evaluate(companion, facts(KINDS[0])).decision == 'pass'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (198, 0)
    assert status['next_candidate'] == None
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
