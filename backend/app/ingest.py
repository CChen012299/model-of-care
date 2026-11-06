"""Load the provided CSVs into the source tables.

The CSVs are treated as a full snapshot: source tables are cleared and
reloaded. Rows that fail validation are skipped and counted rather than
failing the whole load, so one bad row cannot block the worklist.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Diagnosis, Encounter, LabResult, Patient

log = logging.getLogger(__name__)


@dataclass
class TableReport:
    loaded: int = 0
    duplicates: int = 0
    skipped: list[str] = field(default_factory=list)


@dataclass
class LoadReport:
    tables: dict[str, TableReport] = field(default_factory=dict)

    def summary(self) -> str:
        parts = []
        for name, t in self.tables.items():
            parts.append(f"{name}: {t.loaded} loaded, {t.duplicates} duplicates dropped, {len(t.skipped)} skipped")
        return "; ".join(parts)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_date(value: str | None) -> date:
    if not value:
        raise ValueError("missing date")
    return date.fromisoformat(value.strip())


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_csvs(session: Session, data_dir: Path) -> LoadReport:
    report = LoadReport()

    # Children first, so foreign keys never point at a missing patient.
    for model in (Encounter, LabResult, Diagnosis, Patient):
        session.execute(delete(model))

    # Patients
    rep = report.tables["patients"] = TableReport()
    patient_ids: set[str] = set()
    for i, row in enumerate(_read(data_dir / "patients.csv"), start=2):
        try:
            pid = _clean(row["patient_id"])
            if not pid:
                raise ValueError("missing patient_id")
            if pid in patient_ids:
                rep.duplicates += 1
                continue
            session.add(
                Patient(
                    patient_id=pid,
                    first_name=_clean(row["first_name"]) or "",
                    last_name=_clean(row["last_name"]) or "",
                    date_of_birth=_parse_date(row["date_of_birth"]),
                    gender=_clean(row["gender"]) or "",
                    phone=_clean(row["phone"]) or "",
                    language=_clean(row["language"]) or "",
                    pcp_provider_name=_clean(row["pcp_provider_name"]),
                )
            )
            patient_ids.add(pid)
            rep.loaded += 1
        except (ValueError, KeyError) as exc:
            rep.skipped.append(f"patients.csv line {i}: {exc}")
    session.flush()

    def child_rows(filename: str, table: str, build, dedupe_key):
        rep = report.tables[table] = TableReport()
        seen: set[tuple] = set()
        for i, row in enumerate(_read(data_dir / filename), start=2):
            try:
                pid = _clean(row["patient_id"])
                if pid not in patient_ids:
                    raise ValueError(f"unknown patient_id {pid!r}")
                obj = build(pid, row)
                key = dedupe_key(obj)
                if key in seen:
                    rep.duplicates += 1
                    continue
                seen.add(key)
                session.add(obj)
                rep.loaded += 1
            except (ValueError, KeyError) as exc:
                rep.skipped.append(f"{filename} line {i}: {exc}")

    child_rows(
        "diagnoses.csv",
        "diagnoses",
        lambda pid, r: Diagnosis(
            patient_id=pid,
            icd_code=(_clean(r["icd_code"]) or "").upper(),
            description=_clean(r["description"]) or "",
            diagnosed_date=_parse_date(r["diagnosed_date"]),
        ),
        lambda d: (d.patient_id, d.icd_code, d.diagnosed_date),
    )
    child_rows(
        "labs.csv",
        "lab_results",
        lambda pid, r: LabResult(
            patient_id=pid,
            test_name=_clean(r["test_name"]) or "",
            result_value=float(r["result_value"]),
            result_date=_parse_date(r["result_date"]),
        ),
        lambda lab: (lab.patient_id, lab.test_name, lab.result_value, lab.result_date),
    )
    child_rows(
        "encounters.csv",
        "encounters",
        lambda pid, r: Encounter(
            patient_id=pid,
            specialty=_clean(r["specialty"]) or "",
            encounter_date=_parse_date(r["encounter_date"]),
            provider_name=_clean(r["provider_name"]) or "",
        ),
        lambda e: (e.patient_id, e.specialty, e.encounter_date, e.provider_name),
    )

    session.commit()
    for t in report.tables.values():
        for msg in t.skipped:
            log.warning("skipped %s", msg)
    log.info("CSV load complete: %s", report.summary())
    return report
