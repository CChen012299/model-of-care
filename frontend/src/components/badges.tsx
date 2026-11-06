import type { Enrollment, Need, Task } from "../api/types";

export function PriorityBadge({ priority }: { priority: string }) {
  if (priority === "routine") return <span className="muted">routine</span>;
  return <span className={`badge badge-priority-${priority}`}>{priority}</span>;
}

export function TaskTypeBadge({ type }: { type: string }) {
  return <span className={`badge badge-${type}`}>{type}</span>;
}

export function TierLine({ e }: { e: Pick<Enrollment, "program_name" | "tier" | "tier_reason"> }) {
  return (
    <div className="small tier-line" title={e.tier_reason}>
      {e.program_name}: <strong>{e.tier ?? "No tier"}</strong>
    </div>
  );
}

const NEED_LABEL: Record<string, string> = {
  overdue: "overdue",
  never_seen: "never seen",
  scheduled: "scheduled",
  up_to_date: "up to date",
};

export function NeedChip({ need }: { need: Need }) {
  const noPcp = need.target === "PCP" && need.status === "never_seen";
  const label = noPcp ? "no visit on record" : (NEED_LABEL[need.status] ?? need.status);
  const title = [
    `Every ${need.cadence_days} days`,
    need.last_date && `last ${need.last_date}`,
    need.next_scheduled_date && `next ${need.next_scheduled_date}`,
    need.note,
    noPcp && "No task generated: referrals apply to specialists only",
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <span className={`chip chip-${need.status}`} title={title}>
      {need.target} <em>{label}</em>
    </span>
  );
}

export function TaskChip({ task }: { task: Task }) {
  return (
    <span className={`chip chip-task-${task.task_type}`} title={task.reason}>
      {task.target} <em>{task.task_type}</em>
    </span>
  );
}

export function DueCell({ task }: { task: Task }) {
  if (task.task_type === "referral") return <span className="muted">first visit</span>;
  return (
    <span>
      <strong>{task.days_overdue} days</strong>
      <div className="muted small">due {task.due_date}</div>
    </span>
  );
}
