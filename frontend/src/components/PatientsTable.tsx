import type { Patient } from "../api/types";
import { NeedChip, TaskChip, TierLine } from "./badges";

interface Props {
  items: Patient[];
  onOpenPatient: (id: string) => void;
}

export function PatientsTable({ items, onOpenPatient }: Props) {
  if (!items.length) return <p className="empty">No patients match these filters.</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Patient</th>
          <th>Age</th>
          <th>PCP</th>
          <th>Programs and tiers</th>
          <th>Needs</th>
          <th>Open tasks</th>
        </tr>
      </thead>
      <tbody>
        {items.map((p) => (
          <tr key={p.patient_id}>
            <td>
              <button className="link nowrap" onClick={() => onOpenPatient(p.patient_id)}>
                {p.last_name}, {p.first_name}
              </button>
              <div className="muted small">{p.patient_id}</div>
            </td>
            <td>{p.age}</td>
            <td className="small">{p.pcp_provider_name ?? <span className="muted">none assigned</span>}</td>
            <td>
              {p.enrollments.length ? (
                p.enrollments.map((e) => <TierLine key={e.program_id} e={e} />)
              ) : (
                <span className="muted small">Not eligible for any program</span>
              )}
            </td>
            <td>
              <div className="wrap">
                {p.needs.map((n) => (
                  <NeedChip key={n.need_key} need={n} />
                ))}
              </div>
            </td>
            <td>
              <div className="wrap">
                {p.tasks.length ? p.tasks.map((t) => <TaskChip key={t.id} task={t} />) : <span className="muted small">none</span>}
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
