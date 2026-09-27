"""Alaska Rystiggo eligibility, antibody gating, and catalog regressions."""
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
ACHR = 'failed_two_or_more_is_12mo'
MUSK = 'failed_one_or_more_is_and_rituximab_12mo'
PE = 'required_pe_ivig_or_plasmapheresis_with_maintenance'


def pack():
    return json.loads((BASE / 'rule_packs/rystiggo.json').read_text())


def facts():
    return dict(indication='generalized_myasthenia_gravis', age_years=18,
                prescriber_specialty='neurologist_or_consult', mgfa_class='ii_iii_or_iv',
                mg_antibody='achr_positive', mg_adl_score='gte_3',
                no_igg_deficiency_requiring_supplementation='pass',
                not_combined_immunomodulatory_biologic='pass',
                no_active_clinically_significant_infection='pass', immunosuppressive_step=ACHR)


def test_antibody_step_matrix():
    for antibody, allowed in [('achr_positive', ACHR), ('musk_positive', MUSK)]:
        for step in [ACHR, MUSK, PE, 'none']:
            result = evaluate(pack(), dict(facts(), mg_antibody=antibody, immunosuppressive_step=step))
            assert result.decision == ('pass' if step in [allowed, PE] else 'fail')
            assert {c['id'] for c in result.failed_clauses} == (set() if step in [allowed, PE] else {antibody + '_immunosuppressive_step'})
        patient = dict(facts(), mg_antibody=antibody)
        del patient['immunosuppressive_step']
        assert evaluate(pack(), patient).missing_facts == ['immunosuppressive_step']
    patient = facts()
    del patient['mg_antibody']
    del patient['immunosuppressive_step']
    result = evaluate(pack(), patient)
    assert result.decision == 'need_info' and result.missing_facts == ['mg_antibody']
    result = evaluate(pack(), dict(patient, mg_antibody='neither'))
    assert result.decision == 'fail' and not result.missing_facts


def test_missing_and_failed_gates():
    for key in facts():
        patient = facts()
        del patient[key]
        result = evaluate(pack(), patient)
        assert result.decision == 'need_info' and result.missing_facts == [key]
    for key, value in dict(indication='other', age_years=17.999,
                          prescriber_specialty='other', mgfa_class='other', mg_antibody='neither',
                          mg_adl_score='lt_3_or_not_documented',
                          no_igg_deficiency_requiring_supplementation='fail',
                          not_combined_immunomodulatory_biologic='fail',
                          no_active_clinically_significant_infection='fail').items():
        result = evaluate(pack(), dict(facts(), **{key: value}))
        assert result.decision == 'fail' and len(result.failed_clauses) == 1
        assert result.citations
    for invalid in ['yes', 'no', 'unknown', True, False]:
        assert evaluate(pack(), dict(facts(), indication=invalid)).decision == 'fail'
    assert evaluate(pack(), facts()).decision == 'pass'


def test_ui_and_when_metadata():
    p = pack()
    fields = {f['key']: f for f in drug_detail('rystiggo')['fact_fields']}
    assert set(fields) == set(facts())
    for f in fields.values():
        assert f['type'] == 'select' and f['options'] and not f.get('free_text')
    assert fields['immunosuppressive_step']['when'] == {'fact': 'mg_antibody', 'in': ['achr_positive', 'musk_positive']}
    for antibody in ['achr_positive', 'musk_positive']:
        c = next(c for c in p['criteria'] if c['id'] == antibody + '_immunosuppressive_step')
        assert c['when'] == {'fact': 'mg_antibody', 'eq': antibody}
    for opt in fields['age_years']['options']:
        patient = dict(facts(), **_coerce_patient({'age_years': opt['value']}))
        assert evaluate(p, patient).decision == ('pass' if patient['age_years'] >= 18 else 'fail')


def test_catalog_mirror_and_notes():
    p = pack()
    assert p['drug'] == dict(name='Rystiggo', generic_name='rozanolixizumab-noli', therapeutic_class='fc-receptor-blocker')
    assert p['source']['effective_date'] == '2024-11-01'
    assert p['encoding_status'] == 'partial' and p['pdl_status'] == 'unknown'
    assert len(p['criteria']) == 11 and p['max_units'] is None
    assert 'inferred_required_facts' not in p
    assert (BASE / 'rystiggo.json').read_bytes() == (BASE / 'rule_packs/rystiggo.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog == {f.stem: json.loads(f.read_text()) for f in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 82
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 116
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert status['next_candidate'] == 'yorvipath'
    assert status['partial_slugs'] == sorted(k for k,v in catalog.items() if v['encoding_status'] == 'partial')
    for ext in ['json', 'md']:
        assert (BASE / f'ENCODING_STATUS.{ext}').read_bytes() == (BASE.parent / f'ENCODING_STATUS.{ext}').read_bytes()
    notes = ' '.join(p['notes'])
    for text in ['6 weeks', '6 months', '1 point', 'new or worsening', 'treatment limiting', '63 days', 'aseptic meningitis', 'live-attenuated', '24 ml', '36 ml', '840 mg', 'J9333', 'manual review']:
        assert text in notes
