"""Adding programs is a YAML change, overlapping needs merge, and bad config fails at load time."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from app.engine.errors import RulesConfigError
from app.engine.evaluator import evaluate_patient
from app.engine.rules import load_catalog
from tests.conftest import AS_OF, RULES_DIR, days_ago, make_ctx

HYPERTENSION_PROGRAM = """
id: hypertension_management
name: Hypertension Management
eligibility:
  all:
    - age_gte: 18
    - has_diagnosis: { codes: [I10] }
tiers:
  - name: Enrolled
    needs:
      - { type: visit, specialty: Cardiology, every_days: 180 }
"""


@pytest.fixture
def rules_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "rules"
    shutil.copytree(RULES_DIR, dst)
    return dst


def test_new_program_is_just_a_yaml_file(rules_copy):
    (rules_copy / "programs" / "hypertension.yaml").write_text(HYPERTENSION_PROGRAM)
    catalog = load_catalog(rules_copy)
    r = evaluate_patient(make_ctx(dx=("I10",)), catalog, AS_OF)
    assert ("hypertension_management", "Enrolled") in {(e.program_id, e.tier) for e in r.enrollments}
    assert {t.target: t.task_type for t in r.tasks} == {"Cardiology": "referral"}
    # `all` requires every branch: a hypertensive minor is not enrolled.
    minor = evaluate_patient(make_ctx(dob=date(2015, 1, 1), dx=("I10",)), catalog, AS_OF)
    assert minor.enrollments == []


def test_overlapping_needs_merge_to_strictest_cadence(rules_copy):
    (rules_copy / "programs" / "hypertension.yaml").write_text(HYPERTENSION_PROGRAM)
    catalog = load_catalog(rules_copy)
    # High-risk diabetic with hypertension: Diabetes wants Cardiology every 90, Hypertension every 180.
    ctx = make_ctx(dx=("E11.65", "I10"), labs=(("HbA1c", 9.8, days_ago(10)),), enc=(("Cardiology", days_ago(120)),))
    r = evaluate_patient(ctx, catalog, AS_OF)
    cardio = [n for n in r.needs if n.target == "Cardiology"]
    assert len(cardio) == 1
    assert cardio[0].cadence_days == 90
    assert {(s.program_id, s.cadence_days) for s in cardio[0].sources} == {
        ("diabetes_management", 90),
        ("hypertension_management", 180),
    }
    # 120 days since last visit: overdue under the 90-day rule, so exactly one scheduling task.
    assert [(t.target, t.task_type) for t in r.tasks if t.target == "Cardiology"] == [("Cardiology", "scheduling")]


@pytest.mark.parametrize(
    "program_yaml, message",
    [
        ("id: x\nname: X\neligibility: {age_over: 5}\ntiers: [{name: A}]", "unknown condition 'age_over'"),
        ("id: x\nname: X\neligibility: {age_gte: 1}\ntiers: [{name: A, needs: [{type: visit, specialty: Derm, every_days: 9}]}]", "unknown specialty"),
        ("id: x\nname: X\neligibility: {age_gte: 1}\ntiers: [{name: A}, {name: B, when: {age_gte: 2}}]", "only the last tier may omit"),
        ("id: x\nname: X\neligibility: {age_gte: 1}\ntiers: [{name: A, needs: [{type: visit, specialty: PCP, every_days: 0}]}]", "every_days"),
        ("id: x\nname: X\neligibility: {age_gte: 1}\ntiers: [{name: A, needs: [{type: lab_order, test: HbA1c, every_days: 90}]}]", "unknown need type"),
        ("id: x\nname: X\neligibility: {has_diagnosis: {value_set: nope}}\ntiers: [{name: A}]", "unknown value_set"),
        ("id: x\nname: X\neligibility: {latest_lab: {test: HbA1c, within_months: 6}}\ntiers: [{name: A}]", "needs at least one of"),
    ],
)
def test_invalid_rules_fail_at_load_time(rules_copy, program_yaml, message):
    (rules_copy / "programs" / "bad.yaml").write_text(program_yaml)
    with pytest.raises(RulesConfigError, match=message):
        load_catalog(rules_copy)


def test_shipped_rules_load(catalog):
    assert [p.id for p in catalog.programs] == ["diabetes_management", "primary_care_wellness"]
    assert len(catalog.version) == 12
