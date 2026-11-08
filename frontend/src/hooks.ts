import { useEffect, useState, type DependencyList } from "react";
import { EMPTY_FILTERS, type Filters, type Role, type View } from "./api/types";

interface AsyncState<T> {
  data?: T;
  error?: string;
  loading: boolean;
}

/** Run an async loader whenever deps change; aborts the previous request. */
export function useAsync<T>(load: (signal: AbortSignal) => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ loading: true });
  useEffect(() => {
    const ctrl = new AbortController();
    setState((s) => ({ data: s.data, loading: true }));
    load(ctrl.signal)
      .then((data) => setState({ data, loading: false }))
      .catch((err: unknown) => {
        if (!ctrl.signal.aborted) setState({ loading: false, error: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, deps);
  return state;
}

export const PAGE_SIZES = [20, 50, 100] as const;
export const DEFAULT_PAGE_SIZE = 50;

export interface UiState {
  role: Role;
  view: View;
  filters: Filters;
  hasTasks: boolean;
  pageSize: number;
  offset: number;
  patient: string | null;
}

/** UI state lives in the URL, so any view (e.g. ?role=scheduler&specialty=Endocrinology) is linkable. */
export function readUrlState(): UiState {
  const q = new URLSearchParams(window.location.search);
  const filters = { ...EMPTY_FILTERS };
  for (const key of Object.keys(filters) as (keyof Filters)[]) filters[key] = q.get(key) ?? "";
  return {
    role: q.get("role") === "scheduler" ? "scheduler" : "clinical",
    view: q.get("view") === "patients" ? "patients" : "worklist",
    filters,
    hasTasks: q.get("has_tasks") !== "false",
    pageSize: PAGE_SIZES.find((n) => n === Number(q.get("page_size"))) ?? DEFAULT_PAGE_SIZE,
    offset: Number(q.get("offset") ?? 0) || 0,
    patient: q.get("patient"),
  };
}

export function writeUrlState(s: UiState): void {
  const q = new URLSearchParams();
  q.set("role", s.role);
  q.set("view", s.view);
  for (const [k, v] of Object.entries(s.filters)) if (v) q.set(k, v);
  if (s.view === "patients" && !s.hasTasks) q.set("has_tasks", "false");
  if (s.pageSize !== DEFAULT_PAGE_SIZE) q.set("page_size", String(s.pageSize));
  if (s.offset) q.set("offset", String(s.offset));
  if (s.patient) q.set("patient", s.patient);
  window.history.replaceState(null, "", `?${q}`);
}

/** The value, once it has stopped changing for `ms` (used for the search box). */
export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
