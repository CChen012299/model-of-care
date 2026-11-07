"""Read queries behind the API.

Pattern: filter and paginate on IDs in SQL, then load the page's related rows
with a few IN queries (no N+1). Only portable SQL is used (no NULLS LAST, no
tuple IN), so the same code runs on SQLite and SQL Server.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api import schemas
from app.engine.domain import age_on
from app.engine.rules import RuleCatalog
from app.models import Diagnosis, Encounter, EngineRun, Enrollment, LabResult, Need, NeedSource, Patient, Task

_PRIORITY_ORDER = case({"high": 1}, value=Task.priority, else_=0)


def latest_run(session: Session) -> EngineRun | None:
    return session.scalars(
        select(EngineRun).where(EngineRun.finished_at.is_not(None)).order_by(EngineRun.id.desc()).limit(1)
    ).first()


def _summary(p: Patient, run: EngineRun) -> schemas.PatientSummary:
    return schemas.PatientSummary(
        patient_id=p.patient_id,
        first_name=p.first_name,
        last_name=p.last_name,
        age=age_on(p.date_of_birth, run.as_of),
        gender=p.gender,
        phone=p.phone,
        language=p.language,
        pcp_provider_name=p.pcp_provider_name,
    )


def _open_task_filter(types: frozenset[str], specialty: str | None) -> list:
    conds = [Task.status == "open", Task.task_type.in_(sorted(types))]
    if specialty:
        conds.append(Task.target == specialty)
    return conds


def _search_filter(search: str):
    like = f"%{search.strip().lower()}%"
    return or_(
        func.lower(Patient.patient_id).like(like),
        func.lower(Patient.first_name + " " + Patient.last_name).like(like),
    )


# Patients


def list_patients(
    session: Session,
    run: EngineRun,
    *,
    types: frozenset[str],
    specialty: str | None,
    task_filter: bool,
    program: str | None,
    tier: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> schemas.PatientList:
    """task_filter=True means "only patients with at least one matching visible task"."""
    if task_filter and not types:
        return schemas.PatientList(total=0, limit=limit, offset=offset, items=[])

    ids: Select = select(Patient.patient_id)
    if task_filter:
        ids = ids.where(Patient.patient_id.in_(select(Task.patient_id).where(*_open_task_filter(types, specialty))))
    if program or tier:
        enr = select(Enrollment.patient_id)
        if program:
            enr = enr.where(Enrollment.program_id == program)
        if tier:
            enr = enr.where(Enrollment.tier == tier)
        ids = ids.where(Patient.patient_id.in_(enr))
    if search:
        ids = ids.where(_search_filter(search))

    total = session.scalar(select(func.count()).select_from(ids.subquery())) or 0
    page = list(session.scalars(ids.order_by(Patient.patient_id).limit(limit).offset(offset)))
    items = _load_patients(session, run, page, types, specialty)
    return schemas.PatientList(total=total, limit=limit, offset=offset, items=items)


def _load_patients(
    session: Session, run: EngineRun, ids: Sequence[str], types: frozenset[str], specialty: str | None
) -> list[schemas.PatientOut]:
    if not ids:
        return []
    patients = {p.patient_id: p for p in session.scalars(select(Patient).where(Patient.patient_id.in_(ids)))}
    enrollments = defaultdict(list)
    for e in session.scalars(select(Enrollment).where(Enrollment.patient_id.in_(ids)).order_by(Enrollment.program_name)):
        enrollments[e.patient_id].append(schemas.EnrollmentOut.model_validate(e))
    needs = defaultdict(list)
    for n in session.scalars(
        select(Need).where(Need.patient_id.in_(ids)).options(selectinload(Need.sources)).order_by(Need.target)
    ):
        needs[n.patient_id].append(schemas.NeedOut.model_validate(n))
    tasks = defaultdict(list)
    if types:
        q = (
            select(Task)
            .where(Task.patient_id.in_(ids), *_open_task_filter(types, specialty))
            .order_by(_PRIORITY_ORDER.desc(), Task.target)
        )
        for t in session.scalars(q):
            tasks[t.patient_id].append(schemas.TaskOut.model_validate(t))
    return [
        schemas.PatientOut(
            **_summary(patients[pid], run).model_dump(),
            enrollments=enrollments[pid],
            needs=needs[pid],
            tasks=tasks[pid],
        )
        for pid in ids
        if pid in patients
    ]


def get_patient(session: Session, run: EngineRun, patient_id: str, types: frozenset[str]) -> schemas.PatientDetail | None:
    base = _load_patients(session, run, [patient_id], types, None)
    if not base:
        return None
    dx = session.scalars(
        select(Diagnosis).where(Diagnosis.patient_id == patient_id).order_by(Diagnosis.diagnosed_date.desc())
    )
    labs = session.scalars(
        select(LabResult).where(LabResult.patient_id == patient_id).order_by(LabResult.result_date.desc())
    )
    encounters = session.scalars(
        select(Encounter).where(Encounter.patient_id == patient_id).order_by(Encounter.encounter_date.desc())
    )
    return schemas.PatientDetail(
        **base[0].model_dump(),
        diagnoses=[schemas.DiagnosisOut.model_validate(d) for d in dx],
        labs=[schemas.LabOut.model_validate(lab) for lab in labs],
        encounters=[
            schemas.EncounterOut(
                specialty=e.specialty,
                encounter_date=e.encounter_date,
                provider_name=e.provider_name,
                upcoming=e.encounter_date > run.as_of,
            )
            for e in encounters
        ],
    )


# Worklist (tasks)


def list_tasks(
    session: Session,
    run: EngineRun,
    catalog: RuleCatalog,
    *,
    types: frozenset[str],
    specialty: str | None,
    program: str | None,
    tier: str | None,
    search: str | None,
    limit: int,
    offset: int,
) -> schemas.TaskList:
    if not types:
        return schemas.TaskList(total=0, limit=limit, offset=offset, items=[])

    q: Select = select(Task).where(*_open_task_filter(types, specialty))
    if program or tier:
        # A task belongs to a program if that program requested the underlying need.
        src = (
            select(NeedSource.id)
            .join(Need, NeedSource.need_id == Need.id)
            .where(Need.patient_id == Task.patient_id, Need.need_key == Task.need_key)
        )
        if program:
            src = src.where(NeedSource.program_id == program)
        if tier:
            src = src.where(NeedSource.tier == tier)
        q = q.where(src.exists())
    if search:
        q = q.join(Patient, Patient.patient_id == Task.patient_id).where(_search_filter(search))

    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    page = list(
        session.scalars(
            q.order_by(
                _PRIORITY_ORDER.desc(),
                case((Task.days_overdue.is_(None), 1), else_=0),  # portable "NULLS LAST"
                Task.days_overdue.desc(),
                Task.patient_id,
                Task.target,
            )
            .limit(limit)
            .offset(offset)
        )
    )

    pids = sorted({t.patient_id for t in page})
    patients = {p.patient_id: p for p in session.scalars(select(Patient).where(Patient.patient_id.in_(pids)))} if pids else {}
    sources: dict[tuple[str, str], list[schemas.TaskSourceOut]] = defaultdict(list)
    if pids:
        names = {p.id: p.name for p in catalog.programs}
        rows = session.execute(
            select(Need.patient_id, Need.need_key, NeedSource.program_id, NeedSource.tier)
            .join(NeedSource, NeedSource.need_id == Need.id)
            .where(Need.patient_id.in_(pids))
        )
        for pid, key, prog, tr in rows:
            sources[(pid, key)].append(
                schemas.TaskSourceOut(program_id=prog, program_name=names.get(prog, prog), tier=tr)
            )

    items = [
        schemas.WorklistItem(
            task=schemas.TaskOut.model_validate(t),
            patient=_summary(patients[t.patient_id], run),
            sources=sources[(t.patient_id, t.need_key)],
        )
        for t in page
    ]
    return schemas.TaskList(total=total, limit=limit, offset=offset, items=items)
