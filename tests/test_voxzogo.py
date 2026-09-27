"""Voxzogo source-specific approval/denial gates and catalog integration."""
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
INDICATION = 'achondroplasia_increase_linear_growth'
SPECIALTIES = {'endocrinologist', 'pediatric_endocrinologist',
               'endocrinologist_or_pediatric_endocrinologist_consult'}


def load_pack():
    return json.loads((BASE / 'rule_packs/voxzogo.json').read_text())


def base():
    return dict(
        indication=INDICATION, age_years=5, prescriber_specialty='endocrinologist',
        achondroplasia_fgfr3_genetic_confirmation=True,
        baseline_and_ongoing_growth_measurements=True, open_epiphyses=True,
        no_limb_lengthening_surgery_previous_18_months=True,
        no_planned_limb_lengthening_surgery=True,
        no_concurrent_human_growth_hormone=True,
        no_concurrent_insulin_like_growth_factor=True,
        other_causes_of_achondroplasia_or_short_stature_ruled_out=True,
    )


def test_age_boundaries_and_closed_indication():
    for age in [0, 4, 4.999, 5, 5.001, 17, 17.999, 18, 18.001, 80]:
        result = evaluate(load_pack(), dict(base(), age_years=age))
        assert result.decision == ('pass' if 5 <= age < 18 else 'fail')
        if result.decision == 'fail':
            assert [c['id'] for c in result.failed_clauses] == ['age_fda_labeled']
    for indication in ['yes', 'no', 'unknown', True, False, 'other',
                       'short_stature', 'hypochondroplasia']:
        result = evaluate(load_pack(), dict(base(), indication=indication))
        assert result.decision == 'fail'
        assert [c['id'] for c in result.failed_clauses] == ['indication_fda_labeled']


def test_every_ui_option_and_independent_exclusion():
    pack = load_pack()
    fields = {f['key']: f for f in drug_detail('voxzogo')['fact_fields']}
    assert set(fields) == set(base())
    passing = {'indication': {INDICATION}, 'age_years': {'5'},
               'prescriber_specialty': SPECIALTIES}
    ids = {c['required_facts'][0]: c['id'] for c in pack['criteria']}
    for fact, field in fields.items():
        assert field['type'] == 'select' and field['free_text'] is False
        for option in field['options']:
            value = option['value']
            result = evaluate(pack, _coerce_patient(dict(base(), **{fact: value})))
            expected = 'pass' if value in passing.get(fact, {'yes'}) else 'fail'
            assert result.decision == expected, (fact, value, result)
            if expected == 'fail':
                assert [c['id'] for c in result.failed_clauses] == [ids[fact]]
    assert fields['indication']['options'] == [dict(
        value=INDICATION, label='Increase linear growth in achondroplasia with open epiphyses')]
    assert fields['age_years']['options'] == [
        dict(value='4', label='Under 5 years'),
        dict(value='5', label='5 to under 18 years'),
        dict(value='18', label='18 years or older')]


def test_missing_facts():
    for fact in base():
        for omit in [True, False]:
            facts = base()
            if omit:
                del facts[fact]
            else:
                facts[fact] = None
            result = evaluate(load_pack(), facts)
            assert result.decision == 'need_info'
            assert result.missing_facts == [fact]
    assert set(evaluate(load_pack(), {}).missing_facts) == set(base())


def test_metadata_notes_and_catalog():
    pack = load_pack()
    assert pack['drug'] == dict(name='Voxzogo', generic_name='vosoritide',
                                therapeutic_class='growth-hormones')
    assert pack['encoding_status'] == 'partial'
    assert pack['source']['effective_date'] == '2023-01-02'
    assert pack['source']['citation'] == 'https://health.alaska.gov/media/gnkfeftl/202211-voxzogo_criteria_2022.pdf'
    assert pack['source']['criteria_pdf'] == 'data/alaska/raw/202211-voxzogo_criteria_2022.pdf'
    assert (ROOT / pack['source']['criteria_pdf']).exists()
    assert len(pack['criteria']) == 11
    assert 'inferred_required_facts' not in pack
    assert pack['alternatives'] == [] and pack['max_units'] is None
    notes = ' '.join(pack['notes'])
    for text in ['10/16/2022', '11/18/2022', '1/2/2023', 'Accelerated approval',
                 'confirmatory trial(s)', 'initial approval 6 months',
                 'reauthorization 12 months', 'growth velocity AND height',
                 'pre-treatment baseline', 'blood pressure', 'closure of epiphyses',
                 '0.4 mg single-dose vial for reconstitution: 1 vial daily',
                 '0.56 mg single-dose vial for reconstitution: 1 vial daily',
                 '1.2 mg single-dose vial for reconstitution: 1 vial daily', 'manual review']:
        assert text in notes
    assert (BASE / 'voxzogo.json').read_bytes() == (BASE / 'rule_packs/voxzogo.json').read_bytes()
    catalog = load_rule_pack_catalog()
    assert catalog['voxzogo'] == pack
    assert catalog == {p.stem: json.loads(p.read_text()) for p in (BASE / 'rule_packs').glob('*.json')}
    assert json.loads((BASE / 'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE / 'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 115
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 83
    assert catalog['auvelity']['encoding_status'] == 'partial'
    status = json.loads((BASE / 'ENCODING_STATUS.json').read_text())
    assert (status['encoding_partial'], status['encoding_text_only']) == (115, 83)
    assert status['next_candidate'] == 'verquvo'
    assert status['partial_slugs'] == sorted(s for s, p in catalog.items() if p['encoding_status'] == 'partial')
    for name in ['ENCODING_STATUS.json', 'ENCODING_STATUS.md']:
        assert (BASE / name).read_bytes() == (BASE.parent / name).read_bytes()
