"""Xifaxan strength/indication routing, source thresholds and exceptions."""
import gzip
import itertools
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
PACK = json.loads((BASE / 'rule_packs/xifaxan.json').read_text())


def facts(path):
    if path == 'td':
        return dict(product='xifaxan_200mg', indication='travelers_diarrhea',
                    age_years=18, noninvasive_ecoli=True, td_fluoroquinolone='trial')
    if path == 'he':
        return dict(product='xifaxan_550mg', indication='hepatic_encephalopathy',
                    age_years=18, lactulose_response='ineffective')
    return dict(product='xifaxan_550mg', indication='ibs_d', age_years=18,
                ibsd_completed_courses_365_days=2, inpatient_14_day_course_started=False,
                symptom_onset_months_before_diagnosis=6, symptoms_last_3_months=True,
                abdominal_pain_days_per_month=3, improvement_with_defecation=True,
                onset_change_frequency=True, onset_change_stool_appearance=False)


@pytest.mark.parametrize('path', ['td', 'he', 'ibs'])
def test_paths_missing_and_ui(path):
    f = facts(path)
    assert evaluate(PACK, f).decision == 'pass'
    for key in f:
        if key in ['onset_change_stool_appearance', 'inpatient_14_day_course_started']:
            continue  # The other branch already establishes a pass.
        for value in [None, 'omit']:
            incomplete = dict(f, **{key: value})
            if value == 'omit':
                del incomplete[key]
            result = evaluate(PACK, incomplete)
            assert result.decision == 'need_info', (key, result)
            assert key in result.missing_facts
    coerced = _coerce_patient({k: ('yes' if v else 'no') if isinstance(v, bool) else str(v)
                               for k, v in f.items()})
    assert evaluate(PACK, coerced).decision == 'pass'
    detail = drug_detail('xifaxan')
    assert detail['can_evaluate']
    fields = {field['key']: field for field in detail['fact_fields']}
    for key in f:
        assert fields[key]['type'] == 'select'
        assert not fields[key].get('free_text')


@pytest.mark.parametrize('path,key,value', [
    ('td', 'age_years', 11.99), ('td', 'noninvasive_ecoli', False),
    ('td', 'td_fluoroquinolone', 'none'), ('he', 'age_years', 17.99),
    ('he', 'lactulose_response', 'none'), ('ibs', 'age_years', 17.99),
    ('ibs', 'ibsd_completed_courses_365_days', 3),
    ('ibs', 'ibsd_completed_courses_365_days', 4),
    ('ibs', 'symptom_onset_months_before_diagnosis', 5.99),
    ('ibs', 'symptoms_last_3_months', False),
    ('ibs', 'abdominal_pain_days_per_month', 2.99),
])
def test_denials(path, key, value):
    assert evaluate(PACK, dict(facts(path), **{key: value})).decision == 'fail'


@pytest.mark.parametrize('age', [12, 17, 17.99])
def test_pediatric_td_no_fluoroquinolone_required(age):
    f = facts('td')
    del f['td_fluoroquinolone']
    f['age_years'] = age
    assert evaluate(PACK, f).decision == 'pass'


@pytest.mark.parametrize('trial', ['trial', 'allergy', 'culture_sensitivity'])
def test_adult_td_options(trial):
    assert evaluate(PACK, dict(facts('td'), td_fluoroquinolone=trial)).decision == 'pass'


def test_lactulose_subtherapeutic():
    assert evaluate(PACK, dict(facts('he'), lactulose_response='subtherapeutic')).decision == 'pass'


@pytest.mark.parametrize('associations', list(itertools.product([False, True], repeat=3)))
def test_rome_two_of_three(associations):
    f = facts('ibs')
    f.update(zip(['improvement_with_defecation', 'onset_change_frequency',
                  'onset_change_stool_appearance'], associations))
    assert evaluate(PACK, f).decision == ('pass' if sum(associations) >= 2 else 'fail')


def test_inpatient_only_bypasses_rome():
    f = dict(product='xifaxan_550mg', indication='ibs_d', age_years=18,
             ibsd_completed_courses_365_days=2, inpatient_14_day_course_started=True)
    assert evaluate(PACK, f).decision == 'pass'
    for key, value in [('age_years', 17), ('ibsd_completed_courses_365_days', 3)]:
        assert evaluate(PACK, dict(f, **{key: value})).decision == 'fail'
    del f['inpatient_14_day_course_started']
    assert evaluate(PACK, f).decision == 'need_info'


@pytest.mark.parametrize('path', ['td', 'he', 'ibs'])
def test_closed_strength_and_indication(path):
    f = facts(path)
    assert evaluate(PACK, dict(f, product='other')).decision == 'fail'
    assert evaluate(PACK, dict(f, indication='other')).decision == 'fail'
    other = 'xifaxan_550mg' if path == 'td' else 'xifaxan_200mg'
    assert evaluate(PACK, dict(f, product=other)).decision == 'fail'
    irrelevant = dict(noninvasive_ecoli=False, td_fluoroquinolone='none',
                      lactulose_response='none', ibsd_completed_courses_365_days=99,
                      inpatient_14_day_course_started=False)
    irrelevant.update(f)
    assert evaluate(PACK, irrelevant).decision == 'pass'


def test_catalog_metadata_and_notes():
    catalog = load_rule_pack_catalog()
    assert catalog['xifaxan'] == PACK
    assert PACK['drug']['generic_name'] == 'rifaximin'
    assert PACK['drug']['therapeutic_class'] == 'rifamycin-antibacterial'
    assert PACK['source']['effective_date'] == '2016-10-03'
    assert PACK['encoding_status'] == 'partial'
    assert PACK['max_units'] is None
    assert 'inferred_required_facts' not in PACK
    assert evaluate(PACK, {}).decision == 'need_info'
    assert evaluate(PACK, facts('td')).citations == [PACK['source']['citation']]
    notes = ' '.join(PACK['notes'])
    for text in ['3 days', '1 year', '14 days', '4 courses', 'additional travel',
                 '10 weeks', '365 days', '2 tablets/day', '3 tablets/day', 'manual review']:
        assert text in notes
    assert (BASE/'xifaxan.json').read_bytes() == (BASE/'rule_packs/xifaxan.json').read_bytes()
    assert json.loads((BASE/'rule_packs_all.json').read_text()) == catalog
    with gzip.open(BASE/'rule_packs_all.json.gz', 'rt') as stream:
        assert json.load(stream) == catalog
    assert len(catalog) == 198
    assert sum(p['encoding_status'] == 'partial' for p in catalog.values()) == 146
    assert sum(p['encoding_status'] == 'text_only' for p in catalog.values()) == 52
    for folder in [BASE, BASE.parent]:
        status = json.loads((folder/'ENCODING_STATUS.json').read_text())
        assert (status['encoding_partial'], status['encoding_text_only']) == (146, 52)
        assert status['next_candidate'] == 'diclegis-bonjesta'
        assert status['partial_slugs'] == sorted(k for k,p in catalog.items() if p['encoding_status']=='partial')
    assert catalog['bone-resorption-inhibitors']['encoding_status'] == 'partial'
