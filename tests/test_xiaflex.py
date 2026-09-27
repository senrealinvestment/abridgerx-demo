"""Xiaflex: closed indication paths, applicability, source limits and catalog."""
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, get_rule_pack, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
DC = 'dupuytrens_contracture'
PD = 'peyronies_disease'


def pack():
    return json.loads((BASE / 'xiaflex.json').read_text())


def facts(ind):
    f = dict(indication=ind, age_years=18)
    for c in pack()['criteria'][2:]:
        if ind in c['when']['in']:
            f[c['id']] = c['predicate']['value']
    return f


@pytest.mark.parametrize('ind', [DC, PD])
def test_paths_missing_options_and_isolation(ind):
    p = pack()
    f = facts(ind)
    assert evaluate(p, f).decision == 'pass'
    raw = {k: 'yes' if v is True else str(v) for k, v in f.items()}
    assert _coerce_patient(raw) == f
    for k in f:
        missing = dict(f)
        del missing[k]
        result = evaluate(p, missing)
        assert result.decision == 'need_info'
        assert result.missing_facts == [k]
        if k in ['indication', 'age_years']:
            continue
        for option in p['fact_ui'][k]['options']:
            result = evaluate(p, _coerce_patient(dict(raw, **{k: option['value']})))
            assert result.decision == ('pass' if option['value'] == raw[k] else 'fail')
    for age in [0, 17, 17.99, 18, 90]:
        assert evaluate(p, dict(f, age_years=age)).decision == ('pass' if age >= 18 else 'fail')
    other = facts(PD if ind == DC else DC)
    stale = {k: False for k in other if k not in f}
    assert evaluate(p, dict(f, **stale)).decision == 'pass'


def test_closed_indications_and_gates():
    p = pack()
    assert evaluate(p, {}).missing_facts == ['indication']
    for invalid in ['other', 'yes', True, 'erectile_dysfunction', 'ztalmy']:
        result = evaluate(p, {'indication': invalid})
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['indication']
    fields = {f['key']: f for f in drug_detail('xiaflex')['fact_fields']}
    assert set(fields) == set(p['fact_ui'])
    for c in p['criteria']:
        assert fields[c['id']].get('when') == c.get('when')
        assert p['fact_ui'][c['id']].get('when') == c.get('when')
        assert fields[c['id']]['type'] == 'select'
    assert [o['value'] for o in fields['indication']['options']] == [DC, PD]
    labels = ' '.join(o['label'] for o in fields['indication']['options'])
    assert 'palpable cord' in labels and 'palpable plaque' in labels


def test_metadata_limits_and_catalog():
    p = pack()
    assert p['drug'] == dict(name='Xiaflex', generic_name='collagenase_clostridium_histolyticum', therapeutic_class='collagenase')
    assert p['encoding_status'] == 'partial'
    assert p['source']['effective_date'] == '2020-01-06'
    assert 'inferred_required_facts' not in p
    assert p['max_units']['quantity'] == 2 and p['max_units']['days_supply'] is None
    notes = ' '.join(p['notes'])
    for fragment in ['Version 1', '10/23/2019', '11/15/2019', 'one cord affecting two joints', 'two cords affecting two joints', 'one treatment cycle', '4 weeks', '3 cycles', '6 weeks', '15 degree', '4 cycles', 'tendon rupture', 'corporal rupture', 'urethra', 'anticoagulation', 'manual review']:
        assert fragment in notes
    assert (BASE / 'xiaflex.json').read_bytes() == (BASE / 'rule_packs/xiaflex.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert get_rule_pack('xiaflex') == ('xiaflex', p)
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 104
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 94
    assert catalog['crenessity']['encoding_status'] == 'partial'
    assert len(catalog['crenessity']['criteria']) == 7
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (104, 94)
    assert status['next_candidate'] == 'kynamro'
    assert status['partial_slugs'] == sorted(k for k, v in catalog.items() if v['encoding_status'] == 'partial')
    for suffix in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{suffix}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{suffix}').read_bytes()
