import type { SortKey, SortOrder, WorklistItem } from "../api/types";
import { DueCell, PriorityBadge, TaskTypeBadge } from "./badges";

interface Props {
  items: WorklistItem[];
  sort: SortKey;
  order: SortOrder;
  onSort: (key: SortKey) => void;
  onOpenPatient: (id: string) => void;
}

export function WorklistTable({ items, sort, order, onSort, onOpenPatient }: Props) {
  const header = (key: SortKey, label: string) => {
    const active = sort === key;
    return (
      <th aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}>
        <button className={`sort${active ? " active" : ""}`} onClick={() => onSort(key)}>
          {label}
          <span aria-hidden="true">{active ? (order === "asc" ? "↑" : "↓") : "↕"}</span>
        </button>
      </th>
    );
  };
  if (!items.length) return <p className="empty">No open tasks match these filters.</p>;
  return (
    <table>
      <thead>
        <tr>
          {header("priority", "Priority")}
          {header("patient", "Patient")}
          <th>Age</th>
          <th>Language</th>
          <th>Phone</th>
          <th>Specialty</th>
          <th>Task</th>
          <th>Program / tier</th>
          {header("overdue", "Overdue")}
          <th>Why</th>
        </tr>
      </thead>
      <tbody>
        {items.map(({ task, patient, sources }) => (
          <tr key={task.id}>
            <td>
              <PriorityBadge priority={task.priority} />
            </td>
            <td>
              <button className="link nowrap" onClick={() => onOpenPatient(patient.patient_id)}>
                {patient.last_name}, {patient.first_name}
              </button>
              <div className="muted small mono">{patient.patient_id}</div>
            </td>
            <td className="mono">{patient.age}</td>
            <td>{patient.language}</td>
            <td className="nowrap mono">{patient.phone}</td>
            <td>{task.target}</td>
            <td>
              <TaskTypeBadge type={task.task_type} />
            </td>
            <td className="small">
              {sources.map((s) => (
                <div key={s.program_id}>
                  {s.program_name}: <strong>{s.tier}</strong>
                </div>
              ))}
            </td>
            <td className="nowrap">
              <DueCell task={task} />
            </td>
            <td className="small reason">{task.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
