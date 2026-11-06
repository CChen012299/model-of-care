"""API response models (also the source of the frontend's TypeScript types)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EnrollmentOut(_Orm):
    program_id: str
    program_name: str
    tier: str | None
    eligibility_reason: str
    tier_reason: str


class NeedSourceOut(_Orm):
    program_id: str
    tier: str
    cadence_days: int


class NeedOut(_Orm):
    need_key: str
    need_type: str
    target: str
    cadence_days: int
    priority: str
    note: str | None
    status: str
    last_date: date | None
    next_scheduled_date: date | None
    due_date: date | None
    sources: list[NeedSourceOut]


class TaskOut(_Orm):
    id: int
    task_type: str
    target: str
    priority: str
    status: str
    due_date: date | None
    days_overdue: int | None
    reason: str


class PatientSummary(BaseModel):
    patient_id: str
    first_name: str
    last_name: str
    age: int
    gender: str
    phone: str
    language: str
    pcp_provider_name: str | None


class PatientOut(PatientSummary):
    enrollments: list[EnrollmentOut]
    needs: list[NeedOut]
    tasks: list[TaskOut]


class PatientList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PatientOut]


class DiagnosisOut(_Orm):
    icd_code: str
    description: str
    diagnosed_date: date


class LabOut(_Orm):
    test_name: str
    result_value: float
    result_date: date


class EncounterOut(BaseModel):
    specialty: str
    encounter_date: date
    provider_name: str
    upcoming: bool


class PatientDetail(PatientOut):
    diagnoses: list[DiagnosisOut]
    labs: list[LabOut]
    encounters: list[EncounterOut]


class TaskSourceOut(BaseModel):
    """A program/tier that requested the need behind a task."""

    program_id: str
    program_name: str
    tier: str


class WorklistItem(BaseModel):
    task: TaskOut
    patient: PatientSummary
    sources: list[TaskSourceOut]


class TaskList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[WorklistItem]


class ProgramOut(BaseModel):
    id: str
    name: str
    description: str
    tiers: list[str]


class RoleOut(BaseModel):
    role: str
    task_types: list[str]


class RunOut(_Orm):
    id: int
    as_of: date
    rules_version: str
    finished_at: datetime | None
    patients_evaluated: int
    enrollments: int
    needs: int
    tasks_open: int


class Meta(BaseModel):
    run: RunOut
    programs: list[ProgramOut]
    specialties: list[str]
    task_types: list[str]
    roles: list[RoleOut]
