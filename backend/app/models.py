"""Relational schema.

Three groups of tables:

* Source data (patients, diagnoses, lab_results, encounters): what the EHR
  gives us. Loaded from CSV here; in production an EHR sync would write them.
* Derived snapshot (enrollments, needs, need_sources): recomputed on every
  engine run. Pure functions of source data + rules + as-of date, so they are
  replaced wholesale each run.
* Durable work items (tasks): reconciled across runs, never wiped, so staff
  state survives re-runs. A task is keyed by a deterministic task_key, which
  makes runs idempotent.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# --------------------------------------------------------------------------- #
# Source data
# --------------------------------------------------------------------------- #


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    date_of_birth: Mapped[date] = mapped_column(Date)
    gender: Mapped[str] = mapped_column(String(10))
    phone: Mapped[str] = mapped_column(String(30))
    language: Mapped[str] = mapped_column(String(50))
    pcp_provider_name: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    icd_code: Mapped[str] = mapped_column(String(10), index=True)
    description: Mapped[str] = mapped_column(String(255))
    diagnosed_date: Mapped[date] = mapped_column(Date)


class LabResult(Base):
    __tablename__ = "lab_results"
    __table_args__ = (Index("ix_lab_patient_test_date", "patient_id", "test_name", "result_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"))
    test_name: Mapped[str] = mapped_column(String(100))
    result_value: Mapped[float] = mapped_column(Float)
    result_date: Mapped[date] = mapped_column(Date)


class Encounter(Base):
    __tablename__ = "encounters"
    __table_args__ = (Index("ix_enc_patient_specialty_date", "patient_id", "specialty", "encounter_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"))
    specialty: Mapped[str] = mapped_column(String(60))
    encounter_date: Mapped[date] = mapped_column(Date)
    provider_name: Mapped[str] = mapped_column(String(120))


# --------------------------------------------------------------------------- #
# Engine runs and derived snapshot
# --------------------------------------------------------------------------- #


class EngineRun(Base):
    __tablename__ = "engine_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    as_of: Mapped[date] = mapped_column(Date)
    rules_version: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    patients_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    enrollments: Mapped[int] = mapped_column(Integer, default=0)
    needs: Mapped[int] = mapped_column(Integer, default=0)
    tasks_open: Mapped[int] = mapped_column(Integer, default=0)
    tasks_created: Mapped[int] = mapped_column(Integer, default=0)
    tasks_resolved: Mapped[int] = mapped_column(Integer, default=0)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("patient_id", "program_id", name="uq_enrollment_patient_program"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("engine_runs.id"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    program_id: Mapped[str] = mapped_column(String(60), index=True)
    program_name: Mapped[str] = mapped_column(String(120))
    tier: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    # Human-readable evidence, e.g. "HbA1c 9.4 on 2026-01-12 (>= 9.0)". Lets
    # staff (and, later, an LLM summary) see why a patient landed here.
    eligibility_reason: Mapped[str] = mapped_column(String(500))
    tier_reason: Mapped[str] = mapped_column(String(500))


class Need(Base):
    __tablename__ = "needs"
    __table_args__ = (UniqueConstraint("patient_id", "need_key", name="uq_need_patient_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("engine_runs.id"))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    need_key: Mapped[str] = mapped_column(String(120))
    need_type: Mapped[str] = mapped_column(String(30))  # "visit" today; "lab_order" etc. later
    target: Mapped[str] = mapped_column(String(60), index=True)  # specialty, lab test, ...
    cadence_days: Mapped[int] = mapped_column(Integer)
    priority: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # scheduled | up_to_date | overdue | never_seen
    status: Mapped[str] = mapped_column(String(20))
    last_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    sources: Mapped[list[NeedSource]] = relationship(back_populates="need", cascade="all, delete-orphan")


class NeedSource(Base):
    """Which program/tier asked for a need. A need can have several sources
    when programs overlap (e.g. two programs both require Cardiology)."""

    __tablename__ = "need_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    need_id: Mapped[int] = mapped_column(ForeignKey("needs.id", ondelete="CASCADE"), index=True)
    program_id: Mapped[str] = mapped_column(String(60))
    tier: Mapped[str] = mapped_column(String(60))
    cadence_days: Mapped[int] = mapped_column(Integer)

    need: Mapped[Need] = relationship(back_populates="sources")


# --------------------------------------------------------------------------- #
# Durable work items
# --------------------------------------------------------------------------- #


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_task_worklist", "status", "task_type", "target"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # patient | need_key | task_type | cycle. Same inputs always give the same key,
    # so re-running the engine updates tasks instead of duplicating them.
    task_key: Mapped[str] = mapped_column(String(200), unique=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    need_key: Mapped[str] = mapped_column(String(120))
    task_type: Mapped[str] = mapped_column(String(30))  # scheduling | referral
    target: Mapped[str] = mapped_column(String(60))
    priority: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    days_overdue: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(500))
    created_run_id: Mapped[int] = mapped_column(ForeignKey("engine_runs.id"))
    last_seen_run_id: Mapped[int] = mapped_column(ForeignKey("engine_runs.id"))
    resolved_run_id: Mapped[int | None] = mapped_column(ForeignKey("engine_runs.id"), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(120), nullable=True)
