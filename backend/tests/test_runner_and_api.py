"""End to end on the provided CSVs: engine run, re-runs, and the API's role scoping."""
from __future__ import annotations

from collections import Counter
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.main import create_app
from app.db import init_db, make_engine, make_session_factory
from app.engine.runner import run_engine
from app.ingest import load_csvs
from app.models import Task


@pytest.fixture
def session(test_settings):
    engine = make_engine(test_settings.database_url)
    init_db(engine)
    with make_session_factory(engine)() as s:
        load_csvs(s, test_settings.data_dir)
        yield s


@pytest.fixture
def client(test_settings):
    with TestClient(create_app(test_settings)) as c:
        yield c


# --------------------------------------------------------------------------- #
# Loader + runner
# --------------------------------------------------------------------------- #


def test_loader_drops_the_duplicate_encounter(test_settings):
    engine = make_engine(test_settings.database_url)
    init_db(engine)
    with make_session_factory(engine)() as s:
        report = load_csvs(s, test_settings.data_dir)
    assert report.tables["patients"].loaded == 300
    assert report.tables["encounters"].loaded == 1158
    assert report.tables["encounters"].duplicates == 1


def test_expected_totals_on_provided_data(session, catalog):
    run = run_engine(session, catalog, date(2026, 4, 15))
    assert (run.patients_evaluated, run.enrollments, run.needs, run.tasks_open) == (300, 403, 621, 277)
    by_type = dict(session.execute(select(Task.task_type, func.count()).where(Task.status == "open").group_by(Task.task_type)).all())
    assert by_type == {"scheduling": 158, "referral": 119}


def test_rerun_is_idempotent(session, catalog):
    first = run_engine(session, catalog, date(2026, 4, 15))
    second = run_engine(session, catalog, date(2026, 4, 15))
    assert (second.tasks_open, second.tasks_created, second.tasks_resolved) == (first.tasks_open, 0, 0)
    assert session.scalar(select(func.count()).select_from(Task)) == first.tasks_open


def test_reseed_after_run_keeps_tasks(session, catalog, test_settings):
    # Foreign keys are enforced (as on SQL Server): reloading CSVs must not
    # delete patients that enrollments, needs and tasks still reference.
    first = run_engine(session, catalog, date(2026, 4, 15))
    load_csvs(session, test_settings.data_dir)
    second = run_engine(session, catalog, date(2026, 4, 15))
    assert (second.tasks_open, second.tasks_created, second.tasks_resolved) == (first.tasks_open, 0, 0)


def test_rerun_later_resolves_and_creates_tasks(session, catalog):
    run_engine(session, catalog, date(2026, 4, 15))
    later = run_engine(session, catalog, date(2026, 11, 6))
    assert later.tasks_resolved > 0 and later.tasks_created > 0
    assert later.tasks_open == 281
    resolutions = Counter(session.scalars(select(Task.resolution).where(Task.status == "resolved")))
    assert set(resolutions) <= {"Appointment scheduled", "Visit completed", "Superseded by a newer task", "Need no longer applies"}


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


def all_tasks(client, **params):
    return client.get("/api/tasks", params={"limit": 500, **params}).json()["items"]


def test_role_is_required(client):
    assert client.get("/api/tasks").status_code == 400


def test_clinical_sees_scheduling_and_referral(client):
    items = all_tasks(client, role="clinical")
    assert Counter(i["task"]["task_type"] for i in items) == {"scheduling": 158, "referral": 119}


def test_scheduler_sees_only_scheduling(client):
    items = all_tasks(client, role="scheduler")
    assert len(items) == 158
    assert {i["task"]["task_type"] for i in items} == {"scheduling"}


def test_scheduler_cannot_request_referrals(client):
    assert client.get("/api/tasks", params={"role": "scheduler", "task_type": "referral"}).json()["total"] == 0
    r = client.get("/api/patients", headers={"X-Role": "scheduler"}, params={"task_type": "referral"}).json()
    assert r["total"] == 0


def test_role_header_works(client):
    r = client.get("/api/tasks", headers={"X-Role": "scheduler"}, params={"limit": 500}).json()
    assert r["total"] == 158


def test_patients_needing_endocrinology(client):
    r = client.get("/api/patients", params={"role": "clinical", "specialty": "Endocrinology", "limit": 500}).json()
    assert r["total"] == 70
    assert all(t["target"] == "Endocrinology" for p in r["items"] for t in p["tasks"])
    assert all(p["tasks"] for p in r["items"])


def test_patient_list_includes_enrollments_tiers_and_needs(client):
    r = client.get("/api/patients", params={"role": "clinical", "limit": 500}).json()
    assert r["total"] == 300
    minors = [p for p in r["items"] if p["age"] < 18]
    assert len(minors) == 12 and all(not p["enrollments"] for p in minors)


def test_program_and_tier_filters(client):
    items = all_tasks(client, role="clinical", program="diabetes_management", tier="Unmonitored")
    assert items and all(i["task"]["target"] == "Endocrinology" for i in items)
    assert all(any(s["tier"] == "Unmonitored" for s in i["sources"]) for i in items)


def test_worklist_sorted_by_priority_then_overdue(client):
    items = all_tasks(client, role="clinical")
    rank = {"high": 1, "routine": 0}
    keys = [(-rank[i["task"]["priority"]], i["task"]["days_overdue"] is None, -(i["task"]["days_overdue"] or 0)) for i in items]
    assert keys == sorted(keys)


def test_unknown_filters_are_rejected(client):
    assert client.get("/api/tasks", params={"role": "clinical", "specialty": "Dermatology"}).status_code == 400
    assert client.get("/api/tasks", params={"role": "clinical", "program": "nope"}).status_code == 400
    assert client.get("/api/patients/NOPE", params={"role": "clinical"}).status_code == 404


def test_patient_detail_scopes_tasks_by_role(client):
    clinical = client.get("/api/patients/P0002", params={"role": "clinical"}).json()
    scheduler = client.get("/api/patients/P0002", params={"role": "scheduler"}).json()
    assert {t["task_type"] for t in clinical["tasks"]} == {"referral"}
    assert scheduler["tasks"] == []
    assert any(e["upcoming"] for e in clinical["encounters"])
