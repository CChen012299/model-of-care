# Architecture

## Components

```
CSVs -> ingest -> source tables -> engine runner -> enrollments, needs, tasks -> FastAPI -> React
                                   ^ rules/*.yaml
```

* **Ingest** loads the CSVs, drops duplicate rows and skips bad ones with a report.
* **Engine core** (`engine/`) is pure Python. `evaluate_patient(context, catalog,
  as_of)` returns enrollments, needs and draft tasks without touching the database
  or the web layer.
* **Runner** is the only bridge to the database. It replaces the snapshot and
  reconciles tasks.
* **API** serves stored results with role scoping. It never runs rules on a
  request. The **frontend** gets its types from the OpenAPI schema.

All of this runs in one process today. The module boundaries are where separate
services would split.

## Data model

| Group | Tables | Lifecycle |
|---|---|---|
| Source | `patients`, `diagnoses`, `lab_results`, `encounters` | Written by ingest (later, EHR sync) |
| Snapshot | `enrollments`, `needs`, `need_sources` | Replaced each run: a function of data, rules and date |
| Work | `tasks` | Durable, upserted by `task_key` |
| Audit | `engine_runs` | As-of date, rules hash and counts per run |

A need is generic (`need_type`, `target`, `cadence_days`, `priority`).
`need_sources` records which program and tier asked for each need, so one need
can serve several programs. Enrollments store readable evidence, such as
"HbA1c 9.4 on 2026-01-12 (>= 9.0)". The task key is
`patient | need | type | cycle`, so re-runs never duplicate tasks. Tasks that are
no longer needed are resolved with a reason.

## Key decisions and trade-offs

* **Programs are data.** Each program is a YAML file: eligibility, then ordered
  tiers (first match wins), each listing its needs. There is no program-specific
  code.
* **Two small registries instead of a rules DSL.**
  * *Conditions:* `all`, `any`, `age_gte`, `has_diagnosis`, `latest_lab`,
    `no_recent_lab`.
  * *Need types:* `visit`. A need type decides a need's status and which task
    that status calls for.
  * Both are checked when the rules load, so a typo fails at startup. A
    general-purpose DSL would be more flexible, but harder to validate and to
    explain to clinicians.
* **Explicit as-of date.** Rules never read the clock, so runs are reproducible
  and edge cases are testable.
* **Overlapping needs merge.** Each patient gets one need per type and target. The
  shortest cadence wins and every source is kept.
* **Corners cut:**
  * Every run recomputes every patient (about 10 ms for 300).
  * The snapshot is not versioned.
  * There are no task actions yet (claim, complete, dismiss).
  * The role comes from a header instead of an auth token.
  * The code has only been run on SQLite. The SQL is portable and foreign keys
    are enforced.

## Extending

**New program:** add a YAML file. No code changes. A test adds a hypertension
program this way.

**New need type (lab orders):**
1. Add `LabOrderNeed` in `engine/needs.py`. Its `assess` reads lab results
   instead of encounters, and its `task_for` returns a `lab_order` task.
2. Reference it in YAML: `{ type: lab_order, test: HbA1c, every_days: 90 }`.
3. Add `lab_order` to the right roles in `api/roles.py`.

The schema, evaluator, queries and UI stay as they are.

## Scaling

**Thousands of programs.** Index programs by trigger (diagnosis family, age band,
lab test), so each patient is only checked against programs that could apply.
Preview rule changes by dry-running them and diffing the task counts.

**Millions of patients.** Patients are independent, and each takes about 35 µs to
evaluate, so I/O is the bottleneck, not the rules.
* **Event-driven updates:** a new encounter, lab or diagnosis queues that patient
  for a worker.
* **Nightly pass:** catches visits that became overdue.
* **Batch workers:** bulk-load and bulk-write.
* **Reads:** partition tasks and cache worklists in Redis.

On Azure: Container Apps for the API and engine jobs, Service Bus for patient
events, Azure SQL, Azure Cache for Redis, Static Web Apps, DevOps Pipelines and
Terraform.

**EHR scheduling:**
* Write an outbox row in the same transaction as the task update.
* Send it with an idempotency key, retry with backoff, and dead-letter repeated
  failures.
* Show "booking pending" until the EHR confirms.
* The EHR stays the source of truth. The next run resolves the task once the
  booked encounter syncs in.
