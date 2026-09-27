"""Kerendia closed pathways, shared gates, and catalog artifacts."""
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
    return json.loads((BASE / 'rule_packs/kerendia.json').read_text())


INDICATIONS = ['ckd_associated_with_t2dm', 'heart_failure_lvef_ge_40']


def facts(indication):
    return dict(indication=indication, age_years=18,
                cardiologist_or_nephrologist_or_consultation=True,
                baseline_labs_submitted=True,
                **({'ckd_therapy_requirement_met': True} if indication == INDICATIONS[0]
                   else {'hf_therapy_requirement_met': True}),
                concomitant_strong_cyp3a4_inhibitors=False,
                adrenal_insufficiency=False, severe_hepatic_impairment=False)


@pytest.mark.parametrize('indication', INDICATIONS)
def test_paths_and_each_gate(indication):
    patient = facts(indication)
    assert evaluate(pack(), patient).decision == 'pass'
    for key, value in patient.items():
        if key == 'indication':
            continue
        bad = 17.99 if key == 'age_years' else not value
        result = evaluate(pack(), dict(patient, **{key: bad}))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == [key]
        for missing in [None, 'omit']:
            changed = dict(patient, **{key: None})
            if missing == 'omit':
                del changed[key]
            result = evaluate(pack(), changed)
            assert result.decision == 'need_info'
            assert result.missing_facts == [key]
    inactive = 'hf_therapy_requirement_met' if indication == INDICATIONS[0] else 'ckd_therapy_requirement_met'
    assert evaluate(pack(), dict(patient, **{inactive: False})).decision == 'pass'
    strings = {k: ('yes' if v else 'no') if isinstance(v, bool) else str(v) for k, v in patient.items()}
    assert evaluate(pack(), _coerce_patient(strings)).decision == 'pass'


def test_closed_indications_and_when():
    for value in ['other', 'heart_failure', '', True, False]:
        assert evaluate(pack(), dict(facts(INDICATIONS[0]), indication=value)).decision == 'fail'
    patient = facts(INDICATIONS[0])
    del patient['indication']
    del patient['ckd_therapy_requirement_met']
    assert evaluate(pack(), patient).missing_facts == ['indication']
    for clause in pack()['criteria']:
        assert clause.get('when') == pack()['fact_ui'][clause['id']].get('when')


def test_source_and_notes():
    p = pack()
    labels = {k: v['label'] for k, v in p['fact_ui'].items()}
    assert all(t in labels['baseline_labs_submitted'] for t in ['submitted', 'eGFR ≥25', 'UACR ≥30', 'potassium ≤5.0'])
    assert all(t in labels['ckd_therapy_requirement_met'] for t in ['maximally tolerated', 'ACE inhibitor or ARB AND a preferred SGLT2', 'documented contraindication or intolerance'])
    assert 'documented clinical contraindication' in labels['hf_therapy_requirement_met']
    assert 'intolerance' not in labels['hf_therapy_requirement_met']
    assert 'Child-Pugh C' in labels['severe_hepatic_impairment']
    notes = ' '.join(p['notes'])
    assert all(t in notes for t in ['3 months', '6 months', 'stabilization', 'slope of decline', 'no developed hyperkalemia', '30 tablets per 30 days', '10mg and 20mg', 'grapefruit', 'hypotension', 'hyponatremia', 'monitor serum potassium'])


def test_metadata_and_artifacts():
    p = pack()
    assert p['drug'] == dict(name='Kerendia', generic_name='finerenone', therapeutic_class='nonsteroidal-mra')
    assert p['source']['effective_date'] == '2024-01-01'
    assert p['encoding_status'] == 'partial'
    assert p['max_units'] is None and p['alternatives'] == []
    assert 'inferred_required_facts' not in p
    detail = drug_detail('kerendia')
    assert detail['can_evaluate']
    assert {f['key'] for f in detail['fact_fields']} == set(p['fact_ui'])
    assert (BASE / 'kerendia.json').read_bytes() == (BASE / 'rule_packs/kerendia.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['kerendia'] == p
    assert len(catalog) == 198
    assert sum(v['encoding_status'] == 'partial' for v in catalog.values()) == 147
    assert sum(v['encoding_status'] == 'text_only' for v in catalog.values()) == 51
    assert catalog['opsumit']['encoding_status'] == 'partial'
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (147, 51)
    assert status['next_candidate'] == 'fentora'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
