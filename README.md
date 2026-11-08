# Model of Care: Clinical Rules Engine

A small population health engine. It reads patient data, decides which clinical
programs each patient qualifies for, assigns a risk tier, works out what care they
need, and turns each unmet need into a task for the right staff member. A FastAPI
service exposes the results and a React worklist shows them to schedulers and the
clinical team.

**Stack:** Python 3.11+, FastAPI, SQLAlchemy (SQLite by default, SQL Server ready),
React 18 + TypeScript (Vite), pytest.

Architecture, trade-offs and scaling notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Quick start

Requires Python 3.11+ and Node 20+ (tested on Python 3.13 and Node 22).

```bash
# 1. Backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Frontend (build once; FastAPI serves it)
cd ../frontend
npm install
npm run build

# 3. Run
cd ../backend
uvicorn app.api.main:app --port 8000
```

Open **http://localhost:8000**. On first start the server loads `data/*.csv` into
SQLite and runs the engine, so there is no separate seed step.

Interactive API docs: **http://localhost:8000/docs**.

### Frontend dev mode (hot reload)

```bash
cd backend && uvicorn app.api.main:app --reload --port 8000    # terminal 1
cd frontend && npm run dev                                     # terminal 2, http://localhost:5173
```

Vite proxies `/api` to port 8000.

### Tests

```bash
cd backend
pytest
```

72 tests: rule boundaries (age 18/65, A1C 7.0/9.0, the 6-month window, cadence
edges), every chronic ICD family, upcoming visits, never-seen PCP vs specialist,
cross-program need merging, rules config validation, idempotent re-runs and
re-seeding, worklist sorting, and API role scoping on the provided data.

---

## Re-running the engine

```bash
cd backend
python -m app.cli seed                      # reload CSVs, then run
python -m app.cli run                       # run again on loaded data
python -m app.cli run --as-of 2026-11-06    # evaluate as of another date
```

Re-runs are idempotent. Tasks are keyed deterministically, so a re-run updates
existing tasks, creates new ones, and auto-resolves tasks that no longer apply
(for example "Appointment scheduled").

## Configuration

| Variable       | Default                    | Purpose                                      |
|----------------|----------------------------|----------------------------------------------|
| `AS_OF_DATE`   | `2026-04-15`               | Date the rules evaluate against (see below)  |
| `DATABASE_URL` | `sqlite:///backend/care.db`| Any SQLAlchemy URL                           |
| `DATA_DIR`     | `data/`                    | Folder with the four CSVs                    |
| `RULES_DIR`    | `backend/rules/`           | Program, value set and specialty YAML        |

**SQL Server / Azure SQL:** `pip install pyodbc`, then set
`DATABASE_URL="mssql+pyodbc://user:pass@host:1433/db?driver=ODBC+Driver+18+for+SQL+Server"`.
The schema and queries avoid dialect-specific SQL (no `NULLS LAST`, tuple `IN`,
JSON columns or `ON CONFLICT`). I have only run it on SQLite.

---

## API

The caller's role is sent as an `X-Role` header or `?role=` (`scheduler` or
`clinical`). The server enforces it: a scheduler never receives referral tasks,
whatever filters they send.

| Endpoint | Returns |
|---|---|
| `GET /api/meta` | Latest run (as-of date, rules version, counts) and filter options |
| `GET /api/tasks` | The worklist: one row per open task, sorted by priority then most overdue |
| `GET /api/patients` | Patients with enrollments, tiers, needs and the tasks visible to the role |
| `GET /api/patients/{id}` | One patient with diagnoses, labs and encounters, for reviewing a task |

Filters on `/api/tasks` and `/api/patients`: `specialty`, `task_type`
(`scheduling` / `referral`), `program`, `tier`, `search`, `limit`, `offset`.
`/api/patients` also takes `has_tasks=true`. `/api/tasks` also takes
`sort` (`priority`, `patient` or `overdue`) and `order` (`asc` or `desc`); the
default is priority, then most overdue. Unknown filter values return 400
rather than an empty list.

```bash
# All patients who need an endocrinology visit (clinical team)
curl "localhost:8000/api/patients?role=clinical&specialty=Endocrinology"

# A scheduler's worklist
curl -H "X-Role: scheduler" "localhost:8000/api/tasks"

# Referral tasks only
curl "localhost:8000/api/tasks?role=clinical&task_type=referral"
```

## Frontend

* **Role toggle** (top right): Scheduler or Clinical team. The role is sent to the
  API, which does the filtering.
* **Worklist** tab: one row per task with priority, patient contact details,
  specialty, task type, the program and tier that created it, days overdue and the
  reason.
* **Sorting:** click Priority, Patient or Overdue in the worklist header; click again to
  reverse. Sorting happens on the server, so it holds across pages.
* **Patients** tab: one row per patient with programs and tiers, every need and its
  status, and open tasks.
* **Filters:** specialty, task type (only the types the role can see), program, tier,
  name or ID search.
* **Rows per page:** 20, 50 or 100 (default 50), with paging above and below the table.
* Click a patient to see why they landed in each tier, their needs, and their full
  history.
* All UI state is in the URL, so views can be bookmarked, for example
  `/?role=scheduler&specialty=Endocrinology`.

| Scheduler worklist, filtered to Endocrinology | Clinical team, patients view |
|---|---|
| ![Scheduler worklist](docs/screenshots/worklist-scheduler.png) | ![Patients view](docs/screenshots/patients-clinical.png) |

Patient detail: ![Patient detail](docs/screenshots/patient-detail.png)

---

## Project layout

```
data/                         provided CSVs (unchanged)
backend/
  rules/
    programs/*.yaml           one file per clinical program
    value_sets.yaml           named ICD-10 code groups (chronic_conditions, diabetes)
    specialties.yaml          specialties and whether first visits need a referral
  app/
    engine/                   pure rules engine, no DB or web imports
      domain.py               input/output types
      conditions.py           condition registry (age_gte, has_diagnosis, latest_lab, ...)
      needs.py                need type registry (visit) and task policy
      rules.py                YAML loading and validation
      evaluator.py            per-patient pipeline
      runner.py               DB <-> engine, snapshot replace, task reconciliation
    api/                      FastAPI app, role scoping, queries, schemas
    ingest.py                 CSV loader with validation and de-duplication
    models.py                 SQLAlchemy schema
    cli.py                    seed / run / openapi
  tests/
frontend/
  src/api/schema.ts           generated from OpenAPI (npm run gen:types)
  src/components/             worklist, patients table, filters, patient drawer
docs/ARCHITECTURE.md
```

---

## Assumptions

The spec says to make reasonable assumptions and document them. These are mine.

1. **Evaluation date.** All rules depend on "today", so the engine takes an explicit
   as-of date. The data is a snapshot from about mid April 2026: the newest lab is
   2026-04-07, recent A1Cs start on 2025-10-26 with none in the two months before,
   and encounters after about 2026-04-10 look like booked appointments (at most one
   per patient per specialty). I default to **2026-04-15**. Evaluated against the
   real current date, every A1C would be stale (all 115 diabetics Unmonitored) and
   no appointment would count as upcoming.
2. **Age** is whole years on the as-of date. "18 and older" and "65 or older"
   include the birthday itself.
3. **Overdue** means days since the last visit is greater than the cadence. A visit
   exactly 180 days ago on a 180-day cadence is not overdue yet.
4. **Past vs upcoming.** An encounter dated on the as-of day counts as completed.
   Anything later is upcoming, and any upcoming visit for the specialty suppresses
   the task, however far out it is.
5. **"Within the last 6 months"** means on or after the same calendar day six months
   before the as-of date. Labs and diagnoses dated after the as-of date are ignored.
6. **Most recent A1C** in the window decides the tier. Lab and specialty names are
   matched ignoring case and extra spaces.
7. **ICD families** match by prefix ignoring the dot: `E11` matches `E11.65`,
   `G47.3` matches `G47.33` but not `G47.0`.
8. **Never seen a PCP:** no task, per the spec. These patients (72 adults at the
   default date) still show a "no visit on record" PCP need in the UI so they do not
   disappear.
9. **`pcp_provider_name`** is informational. PCP history comes from encounters. 24
   patients have no assigned PCP, and 18 of those have PCP visits anyway.
10. **Overlapping needs.** If two programs ask for the same visit type, the patient
    gets one need with the shortest cadence and highest priority, and every
    requesting program is recorded. This does not happen with the two shipped
    programs, but a test covers it.
11. **Unmonitored diabetics:** "priority: get labs done" is modeled as a high
    priority Endocrinology need with that note, so these tasks sort to the top. No
    lab order is generated, because lab orders are not a need type in the spec (see
    the architecture doc for how to add one).
12. **Role scoping** applies to tasks. Needs and enrollments are shown to both roles.
    In production, PHI fields would be scoped by role as well.
13. **"Patients who need an endocrinology visit"** means patients with an open,
    visible Endocrinology task.
14. **Duplicates.** Exact duplicate CSV rows are dropped at load (one encounter row).
    Rows with bad dates, unknown patient IDs or non-numeric lab values would be
    skipped and logged, not fatal. The provided data has none.

## Results on the provided data (as of 2026-04-15)

| | |
|---|---|
| Primary Care Wellness | 288 eligible: 217 High Priority, 71 Standard (12 patients under 18) |
| Diabetes Management | 115 eligible: 29 High Risk, 39 Moderate, 24 Low, 23 Unmonitored |
| Needs | 621: 158 overdue, 191 never seen, 120 scheduled, 152 up to date |
| Open tasks | 277: 158 scheduling, 119 referral, across 153 patients |

`tests/test_runner_and_api.py` asserts these totals.
