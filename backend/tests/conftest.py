from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.engine.domain import DiagnosisFact, EncounterFact, LabFact, PatientContext
from app.engine.evaluator import evaluate_patient
from app.engine.rules import RuleCatalog, load_catalog
from app.settings import BACKEND_DIR, REPO_DIR, Settings

AS_OF = date(2026, 4, 15)
RULES_DIR = BACKEND_DIR / "rules"
DATA_DIR = REPO_DIR / "data"


def days_ago(n: int) -> date:
    return AS_OF - timedelta(days=n)


def born_years_ago(years: int, days_offset: int = 0) -> date:
    """Birth date such that the patient turns `years` on AS_OF + days_offset."""
    d = AS_OF + timedelta(days=days_offset)
    return d.replace(year=d.year - years)


def make_ctx(
    dob: date = date(1980, 1, 1),
    dx: tuple[str, ...] = (),
    labs: tuple[tuple[str, float, date], ...] = (),
    enc: tuple[tuple[str, date], ...] = (),
    pid: str = "T1",
) -> PatientContext:
    return PatientContext(
        patient_id=pid,
        date_of_birth=dob,
        diagnoses=[DiagnosisFact(code, f"desc {code}", date(2020, 1, 1)) for code in dx],
        labs=[LabFact(test, value, when) for test, value, when in labs],
        encounters=[EncounterFact(spec, when, "Dr. Test") for spec, when in enc],
    )


@pytest.fixture(scope="session")
def catalog() -> RuleCatalog:
    return load_catalog(RULES_DIR)


@pytest.fixture
def evaluate(catalog):
    def run(ctx: PatientContext, as_of: date = AS_OF):
        return evaluate_patient(ctx, catalog, as_of)

    return run


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        data_dir=DATA_DIR,
        rules_dir=RULES_DIR,
        as_of=AS_OF,
        frontend_dist=tmp_path / "no-frontend",
    )
