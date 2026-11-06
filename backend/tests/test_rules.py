"""Program rules from the spec, focused on boundaries and edge cases."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.engine.domain import months_before
from tests.conftest import AS_OF, born_years_ago, days_ago, make_ctx


def tier(result, program_id):
    return next((e.tier for e in result.enrollments if e.program_id == program_id), None)


def tasks_by_target(result):
    return {t.target: t.task_type for t in result.tasks}


PCW, DM = "primary_care_wellness", "diabetes_management"


# --------------------------------------------------------------------------- #
# Primary Care Wellness: eligibility and stratification
# --------------------------------------------------------------------------- #


def test_turning_18_tomorrow_is_not_eligible(evaluate):
    assert tier(evaluate(make_ctx(dob=born_years_ago(18, days_offset=1))), PCW) is None


def test_turning_18_today_is_eligible(evaluate):
    assert tier(evaluate(make_ctx(dob=born_years_ago(18))), PCW) == "Standard"


def test_turning_65_today_is_high_priority(evaluate):
    assert tier(evaluate(make_ctx(dob=born_years_ago(65))), PCW) == "High Priority"


def test_64_without_chronic_dx_is_standard(evaluate):
    assert tier(evaluate(make_ctx(dob=born_years_ago(65, days_offset=1))), PCW) == "Standard"


@pytest.mark.parametrize("code", ["I10", "E11.65", "E10.9", "E78.5", "J45.40", "N18.3", "I25.10", "E03.9", "G47.33", "M81.0"])
def test_any_chronic_family_is_high_priority(evaluate, code):
    assert tier(evaluate(make_ctx(dx=(code,))), PCW) == "High Priority"


def test_non_chronic_dx_is_standard(evaluate):
    # G47.0 (insomnia) is in G47 but not the G47.3 (sleep apnea) family.
    assert tier(evaluate(make_ctx(dx=("G47.0", "J06.9"))), PCW) == "Standard"


# --------------------------------------------------------------------------- #
# Primary Care Wellness: tasks
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "dx, days, expected",
    [
        (("I10",), 180, None),  # High Priority: exactly at cadence is not overdue
        (("I10",), 181, "scheduling"),
        ((), 365, None),  # Standard
        ((), 366, "scheduling"),
    ],
)
def test_pcp_cadence_boundaries(evaluate, dx, days, expected):
    r = evaluate(make_ctx(dx=dx, enc=(("PCP", days_ago(days)),)))
    assert tasks_by_target(r).get("PCP") == expected


def test_no_pcp_history_generates_no_task(evaluate):
    r = evaluate(make_ctx(dx=("I10",)))
    need = next(n for n in r.needs if n.target == "PCP")
    assert need.status == "never_seen"
    assert "PCP" not in tasks_by_target(r)


def test_upcoming_pcp_suppresses_task(evaluate):
    r = evaluate(make_ctx(enc=(("PCP", days_ago(800)), ("PCP", AS_OF + timedelta(days=200)))))
    need = next(n for n in r.needs if n.target == "PCP")
    assert need.status == "scheduled"
    assert r.tasks == []


def test_encounter_on_as_of_date_counts_as_completed(evaluate):
    r = evaluate(make_ctx(enc=(("PCP", AS_OF),)))
    need = next(n for n in r.needs if n.target == "PCP")
    assert need.status == "up_to_date"
    assert need.last_date == AS_OF


def test_specialty_matching_ignores_case_and_spacing(evaluate):
    r = evaluate(make_ctx(enc=((" pcp ", days_ago(10)),)))
    assert next(n for n in r.needs if n.target == "PCP").status == "up_to_date"


# --------------------------------------------------------------------------- #
# Diabetes Management: eligibility and stratification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "a1c, expected",
    [(9.0, "High Risk"), (13.4, "High Risk"), (8.99, "Moderate Risk"), (7.0, "Moderate Risk"), (6.99, "Low Risk")],
)
def test_a1c_tier_boundaries(evaluate, a1c, expected):
    r = evaluate(make_ctx(dx=("E11.9",), labs=(("HbA1c", a1c, days_ago(30)),)))
    assert tier(r, DM) == expected


def test_type_1_is_eligible(evaluate):
    assert tier(evaluate(make_ctx(dx=("E10.65",), labs=(("HbA1c", 6.0, days_ago(5)),))), DM) == "Low Risk"


def test_a1c_without_diabetes_dx_is_not_enrolled(evaluate):
    assert tier(evaluate(make_ctx(labs=(("HbA1c", 10.0, days_ago(5)),))), DM) is None


def test_a1c_exactly_six_months_old_still_counts(evaluate):
    r = evaluate(make_ctx(dx=("E11.9",), labs=(("HbA1c", 9.5, months_before(AS_OF, 6)),)))
    assert tier(r, DM) == "High Risk"


def test_a1c_one_day_past_six_months_is_unmonitored(evaluate):
    stale = months_before(AS_OF, 6) - timedelta(days=1)
    r = evaluate(make_ctx(dx=("E11.9",), labs=(("HbA1c", 9.5, stale),)))
    assert tier(r, DM) == "Unmonitored"


def test_no_a1c_at_all_is_unmonitored_with_priority(evaluate):
    r = evaluate(make_ctx(dx=("E11.9",)))
    assert tier(r, DM) == "Unmonitored"
    endo = next(n for n in r.needs if n.target == "Endocrinology")
    assert (endo.cadence_days, endo.priority, endo.note) == (90, "high", "Priority: get labs done")


def test_most_recent_a1c_wins(evaluate):
    r = evaluate(make_ctx(dx=("E11.9",), labs=(("HbA1c", 10.0, days_ago(90)), ("HbA1c", 6.5, days_ago(10)))))
    assert tier(r, DM) == "Low Risk"


def test_a1c_dated_after_as_of_is_ignored(evaluate):
    r = evaluate(make_ctx(dx=("E11.9",), labs=(("HbA1c", 6.5, AS_OF + timedelta(days=1)),)))
    assert tier(r, DM) == "Unmonitored"


# --------------------------------------------------------------------------- #
# Diabetes Management: tasks
# --------------------------------------------------------------------------- #


def test_high_risk_task_mix(evaluate):
    r = evaluate(
        make_ctx(
            dx=("E11.65",),
            labs=(("HbA1c", 10.2, days_ago(20)),),
            enc=(
                ("Endocrinology", days_ago(91)),  # cadence 90 -> overdue
                ("Podiatry", days_ago(500)),  # overdue, but booked below
                ("Podiatry", AS_OF + timedelta(days=30)),
                ("Ophthalmology", days_ago(365)),  # cadence 365 -> exactly at cadence, fine
                # Cardiology and Nephrology never seen
            ),
        )
    )
    assert tier(r, DM) == "High Risk"
    assert {n.target for n in r.needs} == {"Endocrinology", "Cardiology", "Podiatry", "Ophthalmology", "Nephrology", "PCP"}
    assert tasks_by_target(r) == {"Endocrinology": "scheduling", "Cardiology": "referral", "Nephrology": "referral"}


def test_overdue_task_carries_due_date_and_days_overdue(evaluate):
    r = evaluate(make_ctx(dx=("E11.9",), labs=(("HbA1c", 7.5, days_ago(10)),), enc=(("Endocrinology", days_ago(200)),)))
    task = next(t for t in r.tasks if t.target == "Endocrinology")
    assert task.due_date == days_ago(200) + timedelta(days=180)
    assert task.days_overdue == 20


def test_patient_in_both_programs(evaluate):
    r = evaluate(make_ctx(dob=born_years_ago(70), dx=("E11.9",), labs=(("HbA1c", 6.0, days_ago(10)),)))
    assert {(e.program_id, e.tier) for e in r.enrollments} == {(PCW, "High Priority"), (DM, "Low Risk")}
    assert {n.target for n in r.needs} == {"PCP", "Endocrinology", "Ophthalmology"}


def test_enrollment_reasons_are_human_readable(evaluate):
    r = evaluate(make_ctx(dx=("E11.65",), labs=(("HbA1c", 9.4, days_ago(30)),)))
    dm = next(e for e in r.enrollments if e.program_id == DM)
    assert dm.eligibility_reason == "Dx E11.65 desc E11.65"
    assert dm.tier_reason == f"HbA1c 9.4 on {days_ago(30)} (>= 9.0)"
