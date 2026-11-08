"""FastAPI application.

  uvicorn app.api.main:app --reload

On startup the app loads the rule catalog and, if the database has never been
seeded, loads the CSVs and runs the engine once, so a fresh checkout works
with a single command. If frontend/dist exists it is served at "/".
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.api import queries, schemas
from app.api.roles import ROLE_TASK_TYPES, Role, TaskType, get_role, visible_task_types
from app.db import init_db, make_engine, make_session_factory
from app.engine.domain import norm
from app.engine.rules import RuleCatalog, load_catalog
from app.engine.runner import run_engine
from app.ingest import load_csvs
from app.models import EngineRun
from app.settings import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class RequestContext:
    session: Session
    run: EngineRun
    catalog: RuleCatalog


def get_ctx(request: Request) -> Iterator[RequestContext]:
    with request.app.state.session_factory() as session:
        run = queries.latest_run(session)
        if run is None:
            raise HTTPException(status_code=503, detail="Engine has not run yet. Run: python -m app.cli seed")
        yield RequestContext(session, run, request.app.state.catalog)


# Filter validation: reject typos instead of silently returning nothing


def _specialty(catalog: RuleCatalog, value: str | None) -> str | None:
    if not value:
        return None
    spec = catalog.specialties.get(norm(value))
    if spec is None:
        known = ", ".join(s.name for s in catalog.specialties.values())
        raise HTTPException(status_code=400, detail=f"Unknown specialty {value!r}. Known: {known}")
    return spec.name


def _program_tier(catalog: RuleCatalog, program: str | None, tier: str | None) -> tuple[str | None, str | None]:
    programs = {p.id: p for p in catalog.programs}
    if program and program not in programs:
        raise HTTPException(status_code=400, detail=f"Unknown program {program!r}. Known: {', '.join(programs)}")
    if tier:
        scope = [programs[program]] if program else list(programs.values())
        if not any(t.name == tier for p in scope for t in p.tiers):
            raise HTTPException(status_code=400, detail=f"Unknown tier {tier!r}")
    return program, tier


# Routes

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta", response_model=schemas.Meta)
def meta(ctx: RequestContext = Depends(get_ctx)) -> schemas.Meta:
    """Run info plus the values the frontend needs for its filter dropdowns."""
    return schemas.Meta(
        run=schemas.RunOut.model_validate(ctx.run),
        programs=[
            schemas.ProgramOut(id=p.id, name=p.name, description=p.description, tiers=[t.name for t in p.tiers])
            for p in ctx.catalog.programs
        ],
        specialties=[s.name for s in ctx.catalog.specialties.values()],
        task_types=[t.value for t in TaskType],
        roles=[schemas.RoleOut(role=r.value, task_types=sorted(types)) for r, types in ROLE_TASK_TYPES.items()],
    )


@router.get("/patients", response_model=schemas.PatientList)
def list_patients(
    role: Role = Depends(get_role),
    specialty: str | None = Query(None, description="Only patients with an open task for this specialty"),
    task_type: TaskType | None = Query(None, description="Only patients with an open task of this type"),
    program: str | None = Query(None, description="Only patients enrolled in this program (id)"),
    tier: str | None = Query(None, description="Only patients in this tier"),
    has_tasks: bool = Query(False, description="Only patients with at least one visible open task"),
    search: str | None = Query(None, description="Name or patient ID contains"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ctx: RequestContext = Depends(get_ctx),
) -> schemas.PatientList:
    """Patients with their enrollments, risk tiers, needs and active tasks.

    Tasks are always limited to what the caller's role may see, and narrowed by
    specialty / task_type when given. Needs and enrollments are always complete.
    """
    spec = _specialty(ctx.catalog, specialty)
    program, tier = _program_tier(ctx.catalog, program, tier)
    tt = task_type.value if task_type else None
    return queries.list_patients(
        ctx.session,
        ctx.run,
        types=visible_task_types(role, tt),
        specialty=spec,
        task_filter=bool(spec or tt or has_tasks),
        program=program,
        tier=tier,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/patients/{patient_id}", response_model=schemas.PatientDetail)
def get_patient(
    patient_id: str, role: Role = Depends(get_role), ctx: RequestContext = Depends(get_ctx)
) -> schemas.PatientDetail:
    """One patient with full clinical history, for reviewing a task."""
    detail = queries.get_patient(ctx.session, ctx.run, patient_id, ROLE_TASK_TYPES[role])
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    return detail


@router.get("/tasks", response_model=schemas.TaskList)
def list_tasks(
    role: Role = Depends(get_role),
    specialty: str | None = Query(None),
    task_type: TaskType | None = Query(None),
    program: str | None = Query(None, description="Tasks whose need was requested by this program"),
    tier: str | None = Query(None),
    search: str | None = Query(None, description="Patient name or ID contains"),
    sort: queries.SortKey = Query("priority", description="priority, patient (last, first name) or overdue (days)"),
    order: queries.SortOrder | None = Query(None, description="asc or desc; defaults: priority desc, patient asc, overdue desc"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ctx: RequestContext = Depends(get_ctx),
) -> schemas.TaskList:
    """The worklist: one row per open task. Default order: priority, then most overdue."""
    spec = _specialty(ctx.catalog, specialty)
    program, tier = _program_tier(ctx.catalog, program, tier)
    return queries.list_tasks(
        ctx.session,
        ctx.run,
        ctx.catalog,
        types=visible_task_types(role, task_type.value if task_type else None),
        specialty=spec,
        program=program,
        tier=tier,
        search=search,
        sort=sort,
        order=order or queries.DEFAULT_ORDER[sort],
        limit=limit,
        offset=offset,
    )


# App factory


def create_app(settings: Settings | None = None, *, run_on_startup: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        init_db(engine)
        app.state.session_factory = make_session_factory(engine)
        app.state.catalog = load_catalog(settings.rules_dir)
        if run_on_startup:
            with app.state.session_factory() as session:
                if queries.latest_run(session) is None:
                    log.info("Empty database: loading CSVs from %s and running engine", settings.data_dir)
                    load_csvs(session, settings.data_dir)
                    run_engine(session, app.state.catalog, settings.as_of)
        yield
        engine.dispose()

    app = FastAPI(title="Model of Care: Clinical Rules Engine", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    if (settings.frontend_dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
    return app


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
app = create_app()
