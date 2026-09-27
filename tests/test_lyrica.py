"""Lyrica continuation, indication-specific alternatives, global exclusion and artifacts."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate, _when_applies
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
PACK = json.loads((BASE / 'rule_packs/lyrica.json').read_text())
INDS = [o['value'] for o in PACK['fact_ui']['indication']['options']]
STEPS = [
    {'gabapentin_inadequate': True, 'phn_alternative_failed': True, 'phn_all_alternatives_contraindicated': False},
    {'gabapentin_inadequate': True, 'other_fibromyalgia_therapy_tried_or_evidence': True},
    {'concurrent_aed_inadequate': True},
    {'gabapentin_inadequate': True, 'dpn_alternative_failed': True, 'dpn_all_alternatives_contraindicated': False},
    {'gabapentin_inadequate': True}, {'gabapentin_inadequate': True},
]
def patient(i):
    return dict(indication=INDS[i], continuation_of_care_with_benefit=False,
                not_concurrent_gabapentin=True, **STEPS[i])

@pytest.mark.parametrize('i', range(6))
def test_new_start_and_required_steps(i):
    facts = patient(i)
    assert evaluate(PACK, facts).decision == 'pass'
    for key, value in STEPS[i].items():
        if not value:
            continue
        assert evaluate(PACK, dict(facts, **{key: False})).decision == 'fail'
        missing = dict(facts)
        del missing[key]
        result = evaluate(PACK, missing)
        assert result.decision == 'need_info'
        assert result.missing_facts == [key]
    # A satisfied new-start branch does not require continuation information.
    del facts['continuation_of_care_with_benefit']
    assert evaluate(PACK, facts).decision == 'pass'

@pytest.mark.parametrize('prefix,i', [('phn', 0), ('dpn', 3)])
@pytest.mark.parametrize('failed,all_ci,expected', [(True,False,'pass'),(False,True,'pass'),(True,True,'pass'),(False,False,'fail')])
def test_alternative_logic(prefix,i,failed,all_ci,expected):
    facts=patient(i)
    facts.update({prefix+'_alternative_failed':failed,prefix+'_all_alternatives_contraindicated':all_ci})
    assert evaluate(PACK,facts).decision == expected
    if failed or all_ci:
        del facts[prefix+('_all_alternatives_contraindicated' if failed else '_alternative_failed')]
        assert evaluate(PACK,facts).decision == 'pass'

@pytest.mark.parametrize('indication', INDS + ['off_list', None])
def test_continuation(indication):
    facts=dict(indication=indication,continuation_of_care_with_benefit=True,not_concurrent_gabapentin=True)
    assert evaluate(PACK,facts).decision == 'pass'
    assert evaluate(PACK,dict(facts,not_concurrent_gabapentin=False)).decision == 'fail'
    del facts['not_concurrent_gabapentin']
    assert evaluate(PACK,facts).missing_facts == ['not_concurrent_gabapentin']

@pytest.mark.parametrize('indication', ['other', 'yes', True, False, 'partial_onset_seizures'])
def test_closed_new_starts(indication):
    assert evaluate(PACK,dict(indication=indication,continuation_of_care_with_benefit=False,not_concurrent_gabapentin=True)).decision == 'fail'

@pytest.mark.parametrize('i',range(6))
def test_global_exclusion_and_ui(i):
    facts=patient(i)
    assert evaluate(PACK,dict(facts,not_concurrent_gabapentin=False)).decision == 'fail'
    fields={f['key']:f for f in drug_detail('lyrica')['fact_fields']}
    assert {k for k,v in fields.items() if _when_applies(v.get('when'),facts)} == set(facts)
    submitted={k:('yes' if v is True else 'no' if v is False else v) for k,v in facts.items()}
    assert evaluate(PACK,_coerce_patient(submitted)).decision == 'pass'
    for k in STEPS[i]:
        assert fields[k]['when']['fact'] == 'indication'


def test_unknown_inputs_and_seizure_isolation():
    assert evaluate(PACK,{}).decision == 'need_info'
    facts=patient(2)
    facts.update(gabapentin_inadequate=False,phn_alternative_failed=False,other_fibromyalgia_therapy_tried_or_evidence=False)
    assert evaluate(PACK,facts).decision == 'pass'
    for clause in PACK['criteria']:
        if clause['id'] not in {'approval_path','not_concurrent_gabapentin'}:
            assert clause['when']['fact'] == 'indication'


def test_artifacts():
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert PACK['source']['effective_date'] == '2016-10-03'
    assert (BASE/'lyrica.json').read_bytes() == (BASE/'rule_packs/lyrica.json').read_bytes()
    catalog=load_rule_pack_catalog()
    assert catalog['lyrica'] == PACK
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz','rt') as f:
        assert json.load(f) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status']=='partial' for p in catalog.values()) == 190
    assert sum(p['encoding_status']=='text_only' for p in catalog.values()) == 8
    for directory in [BASE,BASE.parent]:
        status=json.loads((directory/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'],status['encoding_text_only']) == (190,8)
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status']=='partial')
        assert status['next_candidate'] == None
        assert catalog['hemophilia']['encoding_status'] == 'text_only'
    assert (BASE/'ENCODING_STATUS.md').read_bytes() == (BASE.parent/'ENCODING_STATUS.md').read_bytes()
    notes=' '.join(PACK['notes'])
    for term in ['Schedule V','4/6/2016','4/29/2016','10/3/2016','6 months','1 year','3 capsules/day','2 capsules/day','30 mL/day','positive clinical response']:
        assert term in notes
