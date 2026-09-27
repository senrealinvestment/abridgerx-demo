"""Corlanor closed pathways, shared exclusions and catalog artifacts."""
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

def pack():
    return json.loads((BASE / 'rule_packs/corlanor.json').read_text())

INDICATIONS = pack()['criteria'][0]['predicate']['values']

def facts(indication):
    result = {'indication': indication}
    for clause in pack()['criteria'][1:]:
        if clause.get('when', {}).get('eq', indication) == indication:
            result[clause['id']] = clause['predicate']['value']
    return result

@pytest.mark.parametrize('indication', INDICATIONS)
def test_paths_and_each_gate(indication):
    patient = facts(indication)
    assert evaluate(pack(), patient).decision == 'pass'
    for key, value in patient.items():
        if key == 'indication':
            continue
        result = evaluate(pack(), dict(patient, **{key: not value}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [key]
        for missing in [None, 'omit']:
            changed = dict(patient, **{key: None})
            if missing == 'omit':
                del changed[key]
            result = evaluate(pack(), changed)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]

@pytest.mark.parametrize('indication', INDICATIONS)
def test_other_path_facts_ignored_and_ui_coercion(indication):
    patient = facts(indication)
    irrelevant = set(pack()['fact_ui']) - set(patient)
    for key in irrelevant:
        patient[key] = False
    assert evaluate(pack(), patient).decision == 'pass'
    for key, value in facts(indication).items():
        if key == 'indication':
            continue
        for option in pack()['fact_ui'][key]['options']:
            changed = _coerce_patient(dict(patient, **{key: option['value']}))
            assert evaluate(pack(), changed).decision == ('pass' if changed[key] == value else 'fail')
    for clause in pack()['criteria']:
        assert clause.get('when') == pack()['fact_ui'][clause['id']].get('when')

def test_closed_indications():
    for value in ['heart_failure', 'other', True, False, '']:
        assert evaluate(pack(), dict(facts(INDICATIONS[0]), indication=value)).decision != 'pass'
    for value in [None]:
        assert evaluate(pack(), dict(facts(INDICATIONS[0]), indication=value)).decision == 'need_info'
    assert evaluate(pack(), {}).decision == 'need_info'

def test_source_thresholds_exceptions_and_notes():
    p = pack()
    labels = {k: v['label'] for k, v in p['fact_ui'].items()}
    for key, terms in {
        'adult_age_requirement_met': ['≥18', '18 included'],
        'pediatric_age_requirement_met': ['≥6 months', '<18', 'through age 17'],
        'lvef_le_35': ['≤35%', '35 included'],
        'heart_rate_ge_70': ['≥70', '70 included'],
        'adult_beta_blocker_requirement_met': ['failed OR', 'contraindication', 'maximally tolerated'],
        'ist_beta_blocker_requirement_met': ['without adequate response OR', 'contraindication', 'documented intolerance'],
        'conduction_disorder_without_pacemaker': ['Sick sinus', 'sino-atrial', 'third-degree', 'WITHOUT a functioning demand pacemaker'],
        'demand_pacemaker_rate_ge_60': ['≥60', '60 included'],
    }.items():
        assert all(term in labels[key] for term in terms)
    notes = ' '.join(p['notes'])
    for term in ['contraception', 'fetal toxicity', 'atrial fibrillation', 'second degree AV block', 'heart rate throughout', '3 months', '12 months', '60 – 5mg', '60 – 7.5mg', '450ml – 5mg/5ml', 'manual review']:
        assert term in notes

def test_metadata_ui_and_artifacts():
    p = pack()
    assert p['drug'] == dict(name='Corlanor', generic_name='ivabradine', therapeutic_class='hcn-channel-blocker')
    assert p['source']['effective_date'] == '2024-06-01'
    assert p['encoding_status'] == 'partial'
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    assert (ROOT / p['source']['criteria_pdf']).exists()
    detail = drug_detail('corlanor')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(p['fact_ui'])
    assert (BASE / 'corlanor.json').read_bytes() == (BASE / 'rule_packs/corlanor.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['corlanor'] == p
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 173
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 25
    assert catalog['opsumit']['encoding_status'] == 'partial'
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (173, 25)
    assert status['next_candidate'] == 'oxycodone-hydrochloride-immediate-release'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
