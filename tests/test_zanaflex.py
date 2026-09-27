"""Alaska Zanaflex capsule trial and concurrent-tablet exclusion."""
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from engine.evaluate import evaluate
from ui.app import _coerce_patient
from ui.loaders import drug_detail, load_rule_pack_catalog

BASE = ROOT / 'data/alaska/parsed'
STEP = 'comparable_tizanidine_tablets_5_days_without_improvement'
CONCURRENT = 'concurrent_tizanidine_tablets'


def pack():
    return json.loads((BASE / 'rule_packs/zanaflex.json').read_text())


def test_trial_and_concurrent_tablets():
    for trial in [True, False]:
        for concurrent in [True, False]:
            result = evaluate(pack(), {STEP: trial, CONCURRENT: concurrent})
            assert result.decision == ('pass' if trial and not concurrent else 'fail')
            assert {c['id'] for c in result.failed_clauses} == (
                ({STEP} if not trial else set()) | ({CONCURRENT} if concurrent else set()))


def test_missing_facts_and_notes_do_not_add_gates():
    assert set(evaluate(pack(), {}).missing_facts) == {STEP, CONCURRENT}
    for key in [STEP, CONCURRENT]:
        patient = {STEP: True, CONCURRENT: False}
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info' and result.missing_facts == [key]
        patient[key] = None
        assert evaluate(pack(), patient).decision == 'need_info'
    assert evaluate(pack(), {STEP: True, CONCURRENT: False}).decision == 'pass'


def test_ui_and_coercion():
    detail = drug_detail('zanaflex')
    assert detail['can_evaluate']
    fields = {f['key']: f for f in detail['fact_fields']}
    assert set(fields) == {STEP, CONCURRENT} == set(pack()['fact_ui'])
    for key, field in fields.items():
        assert field['type'] == 'select' and not field.get('free_text')
        assert field['options'] == pack()['fact_ui'][key]['options']
        assert [o['value'] for o in field['options']] == ['yes', 'no']
    for trial, concurrent, decision in [('yes', 'no', 'pass'), ('no', 'no', 'fail'), ('yes', 'yes', 'fail')]:
        assert evaluate(pack(), _coerce_patient({STEP: trial, CONCURRENT: concurrent})).decision == decision


def test_metadata_and_catalog():
    p = pack()
    assert p['encoding_status'] == 'partial' and p['requires_pa']
    assert p['source']['effective_date'] == '1970-01-01'
    assert 'inferred_required_facts' not in p and p['alternatives'] == []
    for text in ['2mg', '4mg', '6mg', 'spasticity', 'No prior authorization', 'up to 6 months', 'Version 1', '12/21/2010', '1/21/2011']:
        assert text in ' '.join(p['notes'])
    assert (BASE / 'zanaflex.json').read_bytes() == (BASE / 'rule_packs/zanaflex.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 180
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 18
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only'], status['next_candidate']) == (180, 18, 'brand-name-multisource-medications')
    assert status['partial_slugs'] == sorted(k for k, p in catalog.items() if p['encoding_status'] == 'partial')
    assert catalog['brand-name-multisource-medications']['encoding_status'] == 'text_only'
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
