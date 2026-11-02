"use client";

import { Filter, RotateCcw } from "lucide-react";
import { useState } from "react";
import type { Manifest } from "@/lib/api";
import { useWorkspace, type Filters } from "./workspace";

const DIMS: { key: keyof Filters; label: string }[] = [
  { key: "platform", label: "Platform" },
  { key: "campaign", label: "Campaign" },
  { key: "city", label: "City" },
  { key: "age", label: "Age" },
  { key: "gender", label: "Gender" },
  { key: "device", label: "Device" },
];

/** Shared server-side filters (Overview + Campaigns). Values are validated by the backend. */
export function FilterBar({ dataset }: { dataset: Manifest }) {
  const { filters, setFilters } = useWorkspace();
  const [draft, setDraft] = useState<Filters>(filters);
  const [synced, setSynced] = useState(filters);
  if (synced !== filters) {
    setSynced(filters);
    setDraft(filters);
  }
  const active = Object.keys(filters).length;
  const invalidRange = !!(draft.start_date && draft.end_date && draft.start_date > draft.end_date);
  return (
    <form
      className="panel flat no-print"
      aria-label="Filters"
      onSubmit={(e) => {
        e.preventDefault();
        if (!invalidRange) setFilters(draft);
      }}
    >
      <div className="panel-head" style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Filter size={16} color="var(--teal)" aria-hidden="true" />
          <strong>Filters</strong>
          <span className="faint">
            {active ? `${active} active · applied on the server` : `All rows · ${dataset.date_start} → ${dataset.date_end}`}
          </span>
        </div>
        <div className="btn-row">
          <button className="btn sm ghost" type="button" disabled={!active} onClick={() => setFilters({})}>
            <RotateCcw size={14} /> Reset
          </button>
          <button className="btn sm primary" type="submit" disabled={invalidRange}>
            Apply
          </button>
        </div>
      </div>
      <div className="form-grid">
        <label className="field">
          From
          <input
            className="input"
            type="date"
            min={dataset.date_start}
            max={dataset.date_end}
            value={draft.start_date || ""}
            aria-invalid={invalidRange}
            onChange={(e) => setDraft({ ...draft, start_date: e.target.value })}
          />
        </label>
        <label className="field">
          To
          <input
            className="input"
            type="date"
            min={dataset.date_start}
            max={dataset.date_end}
            value={draft.end_date || ""}
            aria-invalid={invalidRange}
            onChange={(e) => setDraft({ ...draft, end_date: e.target.value })}
          />
        </label>
        {DIMS.filter((d) => dataset.options[d.key]?.length).map((d) => (
          <label className="field" key={d.key}>
            {d.label}
            <select className="select" value={draft[d.key] || ""} onChange={(e) => setDraft({ ...draft, [d.key]: e.target.value })}>
              <option value="">All</option>
              {dataset.options[d.key].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {invalidRange && (
        <p role="alert" style={{ color: "var(--critical)", fontSize: 13, margin: "8px 0 0" }}>
          The start date must not be after the end date.
        </p>
      )}
    </form>
  );
}
