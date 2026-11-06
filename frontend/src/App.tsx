import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import type { Filters, Meta, Role, View } from "./api/types";
import { FilterBar } from "./components/FilterBar";
import { Pager } from "./components/Pager";
import { PatientDrawer } from "./components/PatientDrawer";
import { PatientsTable } from "./components/PatientsTable";
import { WorklistTable } from "./components/WorklistTable";
import { readUrlState, useAsync, writeUrlState, type UiState } from "./hooks";

const PAGE_SIZE = { worklist: 100, patients: 50 } as const;

const ROLE_HELP: Record<Role, string> = {
  scheduler: "Scheduling tasks only: patients already seen by the specialty whose next visit is overdue. Book directly.",
  clinical: "Scheduling and referral tasks. Referrals are first-time specialist visits that need clinical review before booking.",
};

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function App() {
  const meta = useAsync((signal) => api.meta(signal), []);
  if (meta.error) return <p className="error page">Could not reach the API: {meta.error}</p>;
  if (!meta.data) return <p className="muted page">Loading…</p>;
  return <Main meta={meta.data} />;
}

function Main({ meta }: { meta: Meta }) {
  const [ui, setUi] = useState<UiState>(readUrlState);
  useEffect(() => writeUrlState(ui), [ui]);

  const update = (patch: Partial<UiState>) => setUi((s) => ({ ...s, offset: 0, ...patch }));
  const setRole = (role: Role) => {
    // A scheduler cannot filter by a task type they cannot see.
    const allowed = meta.roles.find((r) => r.role === role)?.task_types ?? [];
    const filters = allowed.includes(ui.filters.task_type) ? ui.filters : { ...ui.filters, task_type: "" };
    update({ role, filters });
  };

  const search = useDebounced(ui.filters.search, 250);
  const filters: Filters = { ...ui.filters, search };
  const limit = PAGE_SIZE[ui.view];
  const key = [ui.role, ui.view, JSON.stringify(filters), ui.hasTasks, ui.offset];

  const tasks = useAsync(
    (signal) =>
      ui.view === "worklist" ? api.tasks(ui.role, filters, { limit, offset: ui.offset }, signal) : Promise.resolve(undefined),
    key,
  );
  const patients = useAsync(
    (signal) =>
      ui.view === "patients"
        ? api.patients(ui.role, filters, { hasTasks: ui.hasTasks, limit, offset: ui.offset }, signal)
        : Promise.resolve(undefined),
    key,
  );
  const current = ui.view === "worklist" ? tasks : patients;
  const programNames = useMemo(() => Object.fromEntries(meta.programs.map((p) => [p.id, p.name])), [meta]);
  const closeDrawer = useCallback(() => setUi((s) => ({ ...s, patient: null })), []);

  return (
    <div className="app">
      <header>
        <div>
          <h1>Model of Care Worklist</h1>
          <div className="muted small" title={`Rules version ${meta.run.rules_version}`}>
            Evaluated as of <strong>{meta.run.as_of}</strong> · {meta.run.patients_evaluated} patients
          </div>
        </div>
        <div className="role">
          <span className="muted small">Viewing as</span>
          <div className="segmented" role="group" aria-label="Role">
            {(["scheduler", "clinical"] as Role[]).map((r) => (
              <button key={r} className={ui.role === r ? "active" : ""} onClick={() => setRole(r)}>
                {r === "scheduler" ? "Scheduler" : "Clinical team"}
              </button>
            ))}
          </div>
        </div>
      </header>

      <p className="role-help">{ROLE_HELP[ui.role]}</p>

      <nav className="tabs">
        {(["worklist", "patients"] as View[]).map((v) => (
          <button key={v} className={ui.view === v ? "active" : ""} onClick={() => update({ view: v })}>
            {v === "worklist" ? "Worklist (by task)" : "Patients"}
          </button>
        ))}
      </nav>

      <FilterBar
        meta={meta}
        role={ui.role}
        view={ui.view}
        filters={ui.filters}
        hasTasks={ui.hasTasks}
        onFilters={(f) => update({ filters: f })}
        onHasTasks={(hasTasks) => update({ hasTasks })}
      />

      {current.error && <p className="error">{current.error}</p>}
      <div className={`results ${current.loading ? "loading" : ""}`}>
        {ui.view === "worklist" && tasks.data && (
          <>
            {tasks.data.total > 0 && (
              <div className="count">
                {tasks.data.total} open task{tasks.data.total === 1 ? "" : "s"}
              </div>
            )}
            <WorklistTable items={tasks.data.items} onOpenPatient={(id) => setUi((s) => ({ ...s, patient: id }))} />
            <Pager {...tasks.data} onOffset={(offset) => setUi((s) => ({ ...s, offset }))} />
          </>
        )}
        {ui.view === "patients" && patients.data && (
          <>
            {patients.data.total > 0 && (
              <div className="count">
                {patients.data.total} patient{patients.data.total === 1 ? "" : "s"}
              </div>
            )}
            <PatientsTable items={patients.data.items} onOpenPatient={(id) => setUi((s) => ({ ...s, patient: id }))} />
            <Pager {...patients.data} onOffset={(offset) => setUi((s) => ({ ...s, offset }))} />
          </>
        )}
      </div>

      {ui.patient && (
        <PatientDrawer id={ui.patient} role={ui.role} programNames={programNames} onClose={closeDrawer} />
      )}
    </div>
  );
}
