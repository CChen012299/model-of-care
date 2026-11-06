"""Need type registry.

A need type knows two things:
  1. assess: given a patient's history, is this need scheduled, up to date,
     overdue, or never met?
  2. task_for: what work item (if any) does that state call for, and who is
     it for?

Today there is one need type, "visit". A lab-order need would be a second
class here (assess against lab results instead of encounters, emit a
"lab_order" task) plus one line in the registry. Program YAML, the
evaluator, the schema and the API do not change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from app.engine.domain import NeedResult, NeedSpec, PatientContext, Specialty, TaskDraft, norm
from app.engine.errors import RulesConfigError


@dataclass(frozen=True)
class NeedAssessment:
    status: str  # scheduled | up_to_date | overdue | never_seen
    last_date: date | None
    next_scheduled_date: date | None
    due_date: date | None


class NeedType(ABC):
    name: str
    target_field: str  # the YAML key that names what the need is for

    @abstractmethod
    def validate_target(self, target: str, specialties: Mapping[str, Specialty], path: str) -> str:
        """Check the target at load time; return its canonical spelling."""

    @abstractmethod
    def assess(self, spec: NeedSpec, ctx: PatientContext, as_of: date) -> NeedAssessment: ...

    @abstractmethod
    def task_for(
        self, patient_id: str, need: NeedResult, as_of: date, specialties: Mapping[str, Specialty]
    ) -> TaskDraft | None: ...


class VisitNeed(NeedType):
    """Patient should be seen by `specialty` at least every `every_days` days."""

    name = "visit"
    target_field = "specialty"

    def validate_target(self, target: str, specialties: Mapping[str, Specialty], path: str) -> str:
        spec = specialties.get(norm(target))
        if spec is None:
            raise RulesConfigError(f"{path}: unknown specialty {target!r}; add it to specialties.yaml")
        return spec.name

    def assess(self, spec: NeedSpec, ctx: PatientContext, as_of: date) -> NeedAssessment:
        encounters = ctx.encounters_for(spec.target)
        # An encounter dated on the as-of day counts as completed, not upcoming.
        past = [e.encounter_date for e in encounters if e.encounter_date <= as_of]
        future = [e.encounter_date for e in encounters if e.encounter_date > as_of]
        last = past[-1] if past else None
        upcoming = future[0] if future else None
        due = last + timedelta(days=spec.cadence_days) if last else None

        if upcoming:
            status = "scheduled"
        elif last is None:
            status = "never_seen"
        elif (as_of - last).days > spec.cadence_days:
            status = "overdue"
        else:
            status = "up_to_date"
        return NeedAssessment(status, last, upcoming, due)

    def task_for(
        self, patient_id: str, need: NeedResult, as_of: date, specialties: Mapping[str, Specialty]
    ) -> TaskDraft | None:
        if need.status == "overdue":
            assert need.last_date and need.due_date
            return TaskDraft(
                task_key=f"{patient_id}|{need.need_key}|scheduling|{need.due_date.isoformat()}",
                need_key=need.need_key,
                task_type="scheduling",
                target=need.target,
                priority=need.priority,
                due_date=need.due_date,
                days_overdue=(as_of - need.due_date).days,
                reason=(
                    f"Last {need.target} visit {need.last_date} "
                    f"({(as_of - need.last_date).days} days ago); due every {need.cadence_days} days"
                ),
            )
        if need.status == "never_seen":
            specialty = specialties[norm(need.target)]
            if not specialty.referral_required:
                # Spec: no PCP history means no task (referrals are specialist-only).
                return None
            return TaskDraft(
                task_key=f"{patient_id}|{need.need_key}|referral|first-visit",
                need_key=need.need_key,
                task_type="referral",
                target=need.target,
                priority=need.priority,
                due_date=None,
                days_overdue=None,
                reason=f"No prior {need.target} encounter; clinical review needed before booking",
            )
        return None  # scheduled or up to date


NEED_TYPES: dict[str, NeedType] = {t.name: t for t in (VisitNeed(),)}
