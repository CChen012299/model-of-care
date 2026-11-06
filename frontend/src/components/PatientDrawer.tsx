import { api } from "../api/client";
import type { Role } from "../api/types";
import { useAsync } from "../hooks";
import { DueCell, NeedChip, PriorityBadge, TaskTypeBadge } from "./badges";

interface Props {
  id: string;
  role: Role;
  onClose: () => void;
}

export function PatientDrawer({ id, role, onClose }: Props) {
  const { data: p, error, loading } = useAsync((signal) => api.patient(role, id, signal), [id, role]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close">
          ×
        </button>
        {error && <p className="error">{error}</p>}
        {loading && !p && <p className="muted">Loading…</p>}
        {p && (
          <>
            <h2>
              {p.first_name} {p.last_name} <span className="muted">{p.patient_id}</span>
            </h2>
            <p className="muted">
              {p.age} y · {p.gender} · {p.language} · {p.phone} · PCP: {p.pcp_provider_name ?? "none assigned"}
            </p>

            <h3>Programs</h3>
            {p.enrollments.length === 0 && <p className="muted">Not eligible for any program.</p>}
            {p.enrollments.map((e) => (
              <div key={e.program_id} className="card">
                <strong>{e.program_name}</strong>: {e.tier ?? "No tier"}
                <div className="small">Eligible because: {e.eligibility_reason}</div>
                <div className="small">Tier because: {e.tier_reason}</div>
              </div>
            ))}

            <h3>Open tasks {role === "scheduler" && <span className="muted small">(scheduling only for your role)</span>}</h3>
            {p.tasks.length === 0 && <p className="muted">None.</p>}
            {p.tasks.map((t) => (
              <div key={t.id} className="card">
                <TaskTypeBadge type={t.task_type} /> <strong>{t.target}</strong> <PriorityBadge priority={t.priority} />{" "}
                <DueCell task={t} />
                <div className="small">{t.reason}</div>
              </div>
            ))}

            <h3>Needs</h3>
            <table className="compact">
              <thead>
                <tr>
                  <th>Need</th>
                  <th>Every</th>
                  <th>Last</th>
                  <th>Next booked</th>
                  <th>Requested by</th>
                </tr>
              </thead>
              <tbody>
                {p.needs.map((n) => (
                  <tr key={n.need_key}>
                    <td>
                      <NeedChip need={n} />
                    </td>
                    <td className="nowrap">{n.cadence_days} d</td>
                    <td className="nowrap">{n.last_date ?? "never"}</td>
                    <td className="nowrap">{n.next_scheduled_date ?? "none"}</td>
                    <td className="small">
                      {n.sources.map((s) => `${s.program_id} (${s.tier})`).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h3>Diagnoses</h3>
            <ul className="small">
              {p.diagnoses.map((d) => (
                <li key={`${d.icd_code}${d.diagnosed_date}`}>
                  {d.icd_code} {d.description} <span className="muted">({d.diagnosed_date})</span>
                </li>
              ))}
              {p.diagnoses.length === 0 && <li className="muted">None on record</li>}
            </ul>

            <h3>Labs</h3>
            <ul className="small">
              {p.labs.map((l) => (
                <li key={`${l.test_name}${l.result_date}`}>
                  {l.test_name}: {l.result_value} <span className="muted">({l.result_date})</span>
                </li>
              ))}
              {p.labs.length === 0 && <li className="muted">None on record</li>}
            </ul>

            <h3>Encounters</h3>
            <ul className="small">
              {p.encounters.map((e, i) => (
                <li key={i}>
                  {e.upcoming && <span className="badge badge-scheduled">upcoming</span>} {e.encounter_date} · {e.specialty} ·{" "}
                  {e.provider_name}
                </li>
              ))}
              {p.encounters.length === 0 && <li className="muted">None on record</li>}
            </ul>
          </>
        )}
      </aside>
    </div>
  );
}
