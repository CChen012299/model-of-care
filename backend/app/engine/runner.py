"""Batch run: source tables -> engine -> derived tables.

The only engine module that touches the database. It:
  1. builds a PatientContext per patient from the source tables,
  2. evaluates each one (pure, independent per patient),
  3. replaces the enrollment/need snapshot,
  4. reconciles tasks: create new ones, refresh existing ones, and auto-resolve
     open tasks whose need is no longer actionable (e.g. a visit got booked).

Because each patient is independent, step 2 shards trivially by patient_id
when this moves to a queue of workers (see docs/ARCHITECTURE.md).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.engine.domain import DiagnosisFact, EncounterFact, LabFact, PatientContext, PatientEvaluation
from app.engine.evaluator import evaluate_patient
from app.engine.rules import RuleCatalog
from app.models import (
    Diagnosis,
    Encounter,
    EngineRun,
    Enrollment,
    LabResult,
    Need,
    NeedSource,
    Patient,
    Task,
)

log = logging.getLogger(__name__)

_RESOLUTION_BY_STATUS = {
    "scheduled": "Appointment scheduled",
    "up_to_date": "Visit completed",
    "overdue": "Superseded by a newer task",
    "never_seen": "Superseded by a newer task",
}


def build_contexts(session: Session) -> Iterable[PatientContext]:
    dx: dict[str, list[DiagnosisFact]] = defaultdict(list)
    for d in session.scalars(select(Diagnosis)):
        dx[d.patient_id].append(DiagnosisFact(d.icd_code, d.description, d.diagnosed_date))
    labs: dict[str, list[LabFact]] = defaultdict(list)
    for lab in session.scalars(select(LabResult)):
        labs[lab.patient_id].append(LabFact(lab.test_name, lab.result_value, lab.result_date))
    enc: dict[str, list[EncounterFact]] = defaultdict(list)
    for e in session.scalars(select(Encounter)):
        enc[e.patient_id].append(EncounterFact(e.specialty, e.encounter_date, e.provider_name))
    for p in session.scalars(select(Patient).order_by(Patient.patient_id)):
        yield PatientContext(p.patient_id, p.date_of_birth, dx[p.patient_id], labs[p.patient_id], enc[p.patient_id])


def run_engine(session: Session, catalog: RuleCatalog, as_of: date) -> EngineRun:
    run = EngineRun(as_of=as_of, rules_version=catalog.version, started_at=datetime.now(UTC))
    session.add(run)
    session.flush()

    evaluations: list[PatientEvaluation] = [evaluate_patient(ctx, catalog, as_of) for ctx in build_contexts(session)]

    # Replace the derived snapshot.
    session.execute(delete(NeedSource))
    session.execute(delete(Need))
    session.execute(delete(Enrollment))
    need_status: dict[tuple[str, str], str] = {}
    for ev in evaluations:
        for e in ev.enrollments:
            session.add(
                Enrollment(
                    patient_id=ev.patient_id,
                    program_id=e.program_id,
                    program_name=e.program_name,
                    tier=e.tier,
                    eligibility_reason=e.eligibility_reason,
                    tier_reason=e.tier_reason,
                )
            )
        for n in ev.needs:
            need_status[(ev.patient_id, n.need_key)] = n.status
            session.add(
                Need(
                    patient_id=ev.patient_id,
                    need_key=n.need_key,
                    need_type=n.need_type,
                    target=n.target,
                    cadence_days=n.cadence_days,
                    priority=n.priority,
                    note=n.note,
                    status=n.status,
                    last_date=n.last_date,
                    next_scheduled_date=n.next_scheduled_date,
                    due_date=n.due_date,
                    sources=[NeedSource(program_id=s.program_id, tier=s.tier, cadence_days=s.cadence_days) for s in n.sources],
                )
            )

    # Reconcile durable tasks.
    drafts = {t.task_key: (ev.patient_id, t) for ev in evaluations for t in ev.tasks}
    existing = {t.task_key: t for t in session.scalars(select(Task))}
    created = 0
    for key, (patient_id, d) in drafts.items():
        task = existing.get(key)
        if task is None:
            task = Task(task_key=key, patient_id=patient_id, created_run_id=run.id)
            session.add(task)
            created += 1
        task.need_key = d.need_key
        task.task_type = d.task_type
        task.target = d.target
        task.priority = d.priority
        task.due_date = d.due_date
        task.days_overdue = d.days_overdue
        task.reason = d.reason
        task.status = "open"
        task.resolved_run_id = None
        task.resolution = None

    resolved = 0
    for key, task in existing.items():
        if task.status == "open" and key not in drafts:
            status = need_status.get((task.patient_id, task.need_key))
            task.status = "resolved"
            task.resolved_run_id = run.id
            task.resolution = _RESOLUTION_BY_STATUS[status] if status else "Need no longer applies"
            resolved += 1

    run.patients_evaluated = len(evaluations)
    run.enrollments = sum(len(ev.enrollments) for ev in evaluations)
    run.needs = sum(len(ev.needs) for ev in evaluations)
    run.tasks_open = len(drafts)
    run.tasks_created = created
    run.tasks_resolved = resolved
    run.finished_at = datetime.now(UTC)
    session.commit()
    log.info(
        "Engine run %s as_of=%s rules=%s: %s patients, %s enrollments, %s needs, %s open tasks (+%s new, %s resolved)",
        run.id, as_of, catalog.version, run.patients_evaluated, run.enrollments, run.needs,
        run.tasks_open, created, resolved,
    )
    return run
