import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api/client";
import type { Filters, Meta, Role, View } from "./api/types";
import { FilterBar } from "./components/FilterBar";
import { Pager } from "./components/Pager";
import { PatientDrawer } from "./components/PatientDrawer";
import { PatientsTable } from "./components/PatientsTable";
import { WorklistTable } from "./components/WorklistTable";
import { readUrlState, useAsync, useDebounced, writeUrlState, type UiState } from "./hooks";

const ROLE_HELP: Record<Role, string> = {
  scheduler: "Scheduling tasks only: patients already seen by the specialty whose next visit is overdue. Book directly.",
  clinical: "Scheduling and referral tasks. Referrals are first-time specialist visits that need clinical review before booking.",
};

export default function App() {
  const meta = useAsync((signal) => api.meta(signal), []);
  if (meta.error) return <p className="error page">Could not reach the API: {meta.error}</p>;
  if (!meta.data) return <p className="muted page">Loading…</p>;
  return <Main meta={meta.data} />;
}

function Main({ meta }: { meta: Meta }) {
  const [ui, setUi] = useState<UiState>(readUrlState);
  useEffect(() => writeUrlState(ui), [ui]);

  // Any change except paging goes back to the first page.
  const update = (patch: Partial<UiState>) => setUi((s) => ({ ...s, offset: 0, ...patch }));
  const setRole = (role: Role) => {
    // A scheduler cannot filter by a task type they cannot see.
    const allowed = meta.roles.find((r) => r.role === role)?.task_types ?? [];
    const filters = allowed.includes(ui.filters.task_type) ? ui.filters : { ...ui.filters, task_type: "" };
    update({ role, filters });
  };

  const search = useDebounced(ui.filters.search, 250);
  const view: ViewProps = {
    role: ui.role,
    filters: { ...ui.filters, search },
    limit: ui.pageSize,
    offset: ui.offset,
    onOffset: (offset) => setUi((s) => ({ ...s, offset })),
    onLimit: (pageSize) => update({ pageSize }),
    onOpenPatient: (id) => setUi((s) => ({ ...s, patient: id })),
  };
  const programNames = useMemo(() => Object.fromEntries(meta.programs.map((p) => [p.id, p.name])), [meta]);
  const closeDrawer = useCallback(() => setUi((s) => ({ ...s, patient: null })), []);

  return (
    <div className="app">
      <header>
        <div>
          <div className="overline">Population health worklist</div>
          <h1>Model of Care</h1>
          <div className="meta mono" title={`Rules version ${meta.run.rules_version}`}>
            as of {meta.run.as_of} · {meta.run.patients_evaluated} patients
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

      {ui.view === "worklist" ? <WorklistView {...view} /> : <PatientsView {...view} hasTasks={ui.hasTasks} />}

      {ui.patient && (
        <PatientDrawer id={ui.patient} role={ui.role} programNames={programNames} onClose={closeDrawer} />
      )}
    </div>
  );
}

interface ViewProps {
  role: Role;
  filters: Filters;
  limit: number;
  offset: number;
  onOffset: (offset: number) => void;
  onLimit: (limit: number) => void;
  onOpenPatient: (id: string) => void;
}

function WorklistView({ role, filters, limit, offset, onOffset, onLimit, onOpenPatient }: ViewProps) {
  const { data, error, loading } = useAsync(
    (signal) => api.tasks(role, filters, { limit, offset }, signal),
    [role, JSON.stringify(filters), limit, offset],
  );
  return (
    <div className={`results ${loading ? "loading" : ""}`}>
      {error && <p className="error">{error}</p>}
      {data && (
        <Results total={data.total} limit={limit} noun="open task" pager={<Pager {...data} onOffset={onOffset} onLimit={onLimit} />}>
          <WorklistTable items={data.items} onOpenPatient={onOpenPatient} />
        </Results>
      )}
    </div>
  );
}

function PatientsView({ role, filters, limit, offset, onOffset, onLimit, onOpenPatient, hasTasks }: ViewProps & { hasTasks: boolean }) {
  const { data, error, loading } = useAsync(
    (signal) => api.patients(role, filters, { hasTasks, limit, offset }, signal),
    [role, JSON.stringify(filters), limit, offset, hasTasks],
  );
  return (
    <div className={`results ${loading ? "loading" : ""}`}>
      {error && <p className="error">{error}</p>}
      {data && (
        <Results total={data.total} limit={limit} noun="patient" pager={<Pager {...data} onOffset={onOffset} onLimit={onLimit} />}>
          <PatientsTable items={data.items} onOpenPatient={onOpenPatient} />
        </Results>
      )}
    </div>
  );
}

/** Count and pager above the table; the pager repeats below it when there is more than one page. */
function Results(props: { total: number; limit: number; noun: string; pager: ReactNode; children: ReactNode }) {
  const { total, limit, noun, pager, children } = props;
  if (total === 0) return <>{children}</>;
  return (
    <>
      <div className="results-head">
        <div className="count">{`${total} ${noun}${total === 1 ? "" : "s"}`}</div>
        {pager}
      </div>
      {children}
      {total > limit && <div className="results-foot">{pager}</div>}
    </>
  );
}
