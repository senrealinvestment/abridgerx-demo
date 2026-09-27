"""Alaska Verquvo closed approval routes, denials, and synchronized catalog."""
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
PACK = json.loads((BASE / 'rule_packs/verquvo.json').read_text())
FACTS = dict(indication='symptomatic_chronic_hf_ef_lt_45', age='at_least_18',
             prescriber_specialty='cardiologist', nyha_class='II', ejection_fraction='below_45',
             recent_hf_event='hospitalization_within_6_months', background_raas_therapy='entresto',
             background_beta_blocker='bisoprolol', pregnant='absent', another_sgc_stimulator='absent',
             pde5_inhibitor='absent', daily_dose='at_10_mg')


@pytest.mark.parametrize('key', FACTS)
def test_closed_gates(key):
    clause = next(c for c in PACK['criteria'] if c['id'] == key)
    allowed = clause['predicate']['values']
    for value in [o['value'] for o in PACK['fact_ui'][key]['options']] + ['other', 'yes', 'no', True, False]:
        result = evaluate(PACK, dict(FACTS, **{key: value}))
        assert result.decision == ('pass' if value in allowed else 'fail')
        assert [c['id'] for c in result.failed_clauses] == ([] if value in allowed else [key])
        assert result.citations


@pytest.mark.parametrize('key', FACTS)
@pytest.mark.parametrize('omit', [False, True])
def test_missing(key, omit):
    facts = dict(FACTS, **{key: None})
    if omit:
        del facts[key]
    result = evaluate(PACK, facts)
    assert result.decision == 'need_info'
    assert result.missing_facts == [key]


@pytest.mark.parametrize('raas', ['entresto', 'ace_inhibitor', 'arb', 'contraindicated', 'not_tolerated'])
@pytest.mark.parametrize('beta', ['bisoprolol', 'carvedilol', 'metoprolol_succinate', 'contraindicated', 'not_tolerated'])
@pytest.mark.parametrize('event', ['hospitalization_within_6_months', 'outpatient_iv_diuretics_within_3_months', 'both'])
def test_therapy_and_event_routes_and_denials(raas, beta, event):
    facts = dict(FACTS, background_raas_therapy=raas, background_beta_blocker=beta, recent_hf_event=event)
    assert evaluate(PACK, facts).decision == 'pass'
    for key, value in [('pregnant', 'present'), ('another_sgc_stimulator', 'present'),
                       ('pde5_inhibitor', 'present'), ('daily_dose', 'above_10_mg'),
                       ('background_raas_therapy', 'none'), ('background_beta_blocker', 'none')]:
        result = evaluate(PACK, dict(facts, **{key: value}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [key]


def test_ui_and_source_metadata():
    detail = drug_detail('verquvo')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == set(FACTS)
    assert len(fields['indication']['options']) == 1
    assert all(f['type'] == 'select' and not f.get('free_text') for f in fields.values())
    assert evaluate(PACK, _coerce_patient(FACTS)).decision == 'pass'
    assert PACK['drug']['generic_name'] == 'vericiguat'
    assert PACK['drug']['therapeutic_class'] == 'sgc-stimulator'
    assert PACK['source']['effective_date'] == '2022-01-04'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None and PACK['alternatives'] == []
    assert 'inferred_required_facts' not in PACK
    for text in ['ESRD', 'hepatic insufficiency', 'breastfeeding', '3 months', '12 months',
                 'positive clinical response', '30 tablets per 30 days', '2.5 mg, 5 mg, and 10 mg', 'manual review']:
        assert text in ' '.join(PACK['notes'])


def test_catalog_and_mirrors():
    catalog = load_rule_pack_catalog()
    assert catalog['verquvo'] == PACK
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert (BASE / 'verquvo.json').read_bytes() == (BASE / 'rule_packs/verquvo.json').read_bytes()
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 178
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 20
    assert catalog['interleukin-5-inhibitors']['encoding_status'] == 'partial'
    for directory in [BASE, BASE.parent]:
        status = json.loads((directory / 'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (178, 20)
        assert status['next_candidate'] == 'oral-buprenorphine-based-medication-assisted-therapy-office-based-opioid-treatme'
        assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
