import type { Filters, Meta, PatientDetail, PatientList, Role, TaskList } from "./types";

type Params = Record<string, string | number | boolean | undefined>;

async function get<T>(path: string, role: Role | null, params: Params = {}, signal?: AbortSignal): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "" && v !== false) qs.set(k, String(v));
  }
  const headers: HeadersInit = role ? { "X-Role": role } : {};
  const query = qs.toString();
  const res = await fetch(`/api${path}${query ? `?${query}` : ""}`, { headers, signal });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: (signal?: AbortSignal) => get<Meta>("/meta", null, {}, signal),

  tasks: (role: Role, f: Filters, page: { limit: number; offset: number }, signal?: AbortSignal) =>
    get<TaskList>("/tasks", role, { ...f, ...page }, signal),

  patients: (
    role: Role,
    f: Filters,
    opts: { hasTasks: boolean; limit: number; offset: number },
    signal?: AbortSignal,
  ) => get<PatientList>("/patients", role, { ...f, has_tasks: opts.hasTasks, limit: opts.limit, offset: opts.offset }, signal),

  patient: (role: Role, id: string, signal?: AbortSignal) =>
    get<PatientDetail>(`/patients/${encodeURIComponent(id)}`, role, {}, signal),
};
