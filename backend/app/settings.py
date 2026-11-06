"""Runtime configuration, read from environment variables.

Everything has a default so the app runs locally with zero setup.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

# The provided dataset is a snapshot taken around mid April 2026: the newest
# lab is 2026-04-07, and encounters after ~2026-04-10 look like booked future
# appointments. Evaluating against the real current date would make every A1C
# "stale" and every appointment "past". See README > Assumptions.
DEFAULT_AS_OF = "2026-04-15"


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    rules_dir: Path
    as_of: date
    frontend_dist: Path


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'care.db'}"),
        data_dir=Path(os.getenv("DATA_DIR", REPO_DIR / "data")),
        rules_dir=Path(os.getenv("RULES_DIR", BACKEND_DIR / "rules")),
        as_of=date.fromisoformat(os.getenv("AS_OF_DATE", DEFAULT_AS_OF)),
        frontend_dist=Path(os.getenv("FRONTEND_DIST", REPO_DIR / "frontend" / "dist")),
    )
