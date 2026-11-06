import type { Filters, Meta, Role, View } from "../api/types";

interface Props {
  meta: Meta;
  role: Role;
  view: View;
  filters: Filters;
  hasTasks: boolean;
  onFilters: (f: Filters) => void;
  onHasTasks: (v: boolean) => void;
}

export function FilterBar({ meta, role, view, filters, hasTasks, onFilters, onHasTasks }: Props) {
  const allowedTypes = meta.roles.find((r) => r.role === role)?.task_types ?? [];
  const program = meta.programs.find((p) => p.id === filters.program);
  const tiers = program ? program.tiers : [...new Set(meta.programs.flatMap((p) => p.tiers))];
  const set = (patch: Partial<Filters>) => onFilters({ ...filters, ...patch });
  const active = Object.values(filters).some(Boolean);

  return (
    <div className="filters">
      <label>
        Specialty
        <select value={filters.specialty} onChange={(e) => set({ specialty: e.target.value })}>
          <option value="">All</option>
          {meta.specialties.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <label>
        Task type
        <select value={filters.task_type} onChange={(e) => set({ task_type: e.target.value })}>
          <option value="">All visible</option>
          {allowedTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      <label>
        Program
        <select value={filters.program} onChange={(e) => set({ program: e.target.value, tier: "" })}>
          <option value="">All</option>
          {meta.programs.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Tier
        <select value={filters.tier} onChange={(e) => set({ tier: e.target.value })}>
          <option value="">All</option>
          {tiers.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </label>
      <label className="grow">
        Search
        <input
          type="search"
          placeholder="Name or patient ID"
          value={filters.search}
          onChange={(e) => set({ search: e.target.value })}
        />
      </label>
      {view === "patients" && (
        <label className="checkbox">
          <input type="checkbox" checked={hasTasks} onChange={(e) => onHasTasks(e.target.checked)} />
          Only patients with open tasks
        </label>
      )}
      {active && (
        <button className="link" onClick={() => onFilters({ specialty: "", task_type: "", program: "", tier: "", search: "" })}>
          Clear filters
        </button>
      )}
    </div>
  );
}
