"use client";

import { Check, ChevronLeft, ChevronRight, Download, FileUp, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  api,
  errorText,
  isAbort,
  PLATFORMS,
  post,
  type ImportOptions,
  type Manifest,
  type Platform,
  type Row,
  type Stage,
  type ValidationReport,
} from "@/lib/api";
import { coverage, dateTime, num, shortId, sourceKind } from "@/lib/format";
import { Busy, ConfirmDialog, Empty, LoadingPage, Notice, PageHead, Panel, Segmented, SourceBadge } from "./ui";
import { useWorkspace } from "./workspace";

const REQUIRED = ["date", "campaign", "platform", "impressions", "clicks", "spend", "conversions", "revenue", "age", "gender", "city", "device"];
const EXTRA = ["campaign_id", "account_id", "attribution_window", "conversion_definition"];

function RowsTable({ columns, rows, caption }: { columns: string[]; rows: Row[]; caption: string }) {
  return (
    <div className="table-wrap" style={{ maxHeight: 360 }}>
      <table className="data">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} style={r[c] == null || r[c] === "" ? { color: "var(--text-3)" } : undefined}>
                  {r[c] == null || r[c] === "" ? "—" : String(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DatasetPreview({ dataset }: { dataset: Manifest }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ columns: string[]; rows: Row[]; total: number } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    api<{ columns: string[]; rows: Row[]; total: number }>(`/datasets/${dataset.id}/preview?page=${page}&page_size=20`, { signal: c.signal })
      .then(setData)
      .catch((e) => !isAbort(e) && setError(errorText(e)));
    return () => c.abort();
  }, [dataset.id, page]);
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data) return <Busy text="Loading rows…" />;
  const pages = Math.ceil(data.total / 20);
  return (
    <div className="grid" style={{ gap: 10 }}>
      <RowsTable columns={data.columns} rows={data.rows} caption={`Rows of ${dataset.name}, page ${page}`} />
      <div className="btn-row" style={{ justifyContent: "space-between" }}>
        <span className="faint num">
          Page {page} of {pages} · {num(data.total)} stored rows
        </span>
        <div className="btn-row">
          <button className="btn sm" type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous rows">
            <ChevronLeft size={15} />
          </button>
          <button className="btn sm" type="button" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next rows">
            <ChevronRight size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}

function SavedDatasets() {
  const { state, select, refresh } = useWorkspace();
  const [open, setOpen] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Manifest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!state) return null;
  if (!state.datasets.length)
    return (
      <Empty title="No saved campaign datasets yet">
        Generate a synthetic demo or import a CSV below. Saved sources stay isolated from each other and keep their provenance.
      </Empty>
    );
  return (
    <Panel title="Saved campaign datasets" description="Select the source every analysis screen reads. Real and synthetic sources are never mixed.">
      {error && <Notice tone="error">{error}</Notice>}
      <div className="grid" style={{ gap: 10 }}>
        {state.datasets.map((d) => {
          const selected = d.id === state.selected_dataset_id;
          return (
            <article key={d.id} className="panel flat" style={{ padding: 14, borderColor: selected ? "var(--teal)" : undefined }}>
              <div className="panel-head" style={{ marginBottom: 6 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <strong>{d.name}</strong>
                    <SourceBadge dataset={d} />
                    {selected && <span className="badge teal">Selected</span>}
                  </div>
                  <div className="faint num">
                    {num(d.rows)} rows · {d.date_start} → {d.date_end} · {d.date_granularity} · {d.options.platform?.join(", ")} · id {shortId(d.id)}
                  </div>
                </div>
                <div className="btn-row">
                  {!selected && (
                    <button
                      className="btn sm primary"
                      type="button"
                      disabled={busy}
                      onClick={async () => {
                        setError("");
                        try {
                          await select(d.id);
                        } catch (e) {
                          setError(errorText(e));
                        }
                      }}
                    >
                      Select
                    </button>
                  )}
                  <button className="btn sm" type="button" aria-expanded={open === d.id} onClick={() => setOpen(open === d.id ? null : d.id)}>
                    {open === d.id ? "Hide" : "Inspect"}
                  </button>
                  <a className="btn sm" href={`/api/v1/datasets/${d.id}/export`} download>
                    <Download size={14} /> CSV
                  </a>
                  <button className="btn sm danger" type="button" onClick={() => setDeleting(d)} aria-label={`Delete ${d.name}`}>
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {open === d.id && (
                <div className="grid" style={{ gap: 12, marginTop: 10 }}>
                  <dl className="dl">
                    <dt>Kind</dt>
                    <dd>{sourceKind(d)}</dd>
                    <dt>Saved</dt>
                    <dd>{dateTime(d.imported_at)}</dd>
                    {d.original_filename && (
                      <>
                        <dt>File</dt>
                        <dd>
                          {d.original_filename} ({d.import_profile})
                        </dd>
                      </>
                    )}
                    {d.seed != null && (
                      <>
                        <dt>Seed</dt>
                        <dd className="num">{d.seed}</dd>
                      </>
                    )}
                    <dt>Currency</dt>
                    <dd>{d.original_currency === "PKR" ? "PKR" : `${d.original_currency} → PKR at ${d.exchange_rate}`}</dd>
                    <dt>Conversions</dt>
                    <dd>{d.conversion_definition}</dd>
                    <dt>Attribution</dt>
                    <dd>{d.attribution_window}</dd>
                    <dt>Revenue usable</dt>
                    <dd>{d.data_ready_for_revenue ? "Yes" : "No: revenue planning is blocked"}</dd>
                    <dt>Coverage</dt>
                    <dd className="num">
                      {Object.entries(d.coverage)
                        .map(([k, v]) => `${k} ${coverage(v)}`)
                        .join(" · ")}
                    </dd>
                  </dl>
                  {d.warnings.map((w) => (
                    <Notice key={w} tone="warn">
                      {w}
                    </Notice>
                  ))}
                  <DatasetPreview dataset={d} />
                </div>
              )}
            </article>
          );
        })}
      </div>
      <ConfirmDialog
        open={!!deleting}
        title={`Delete “${deleting?.name}”?`}
        confirmLabel="Delete dataset"
        busy={busy}
        onClose={() => setDeleting(null)}
        onConfirm={async () => {
          if (!deleting) return;
          setBusy(true);
          setError("");
          try {
            await api(`/datasets/${deleting.id}`, { method: "DELETE" });
            setDeleting(null);
            await refresh();
          } catch (e) {
            setError(errorText(e));
            setDeleting(null);
          } finally {
            setBusy(false);
          }
        }}
      >
        This permanently removes the stored rows and everything derived from them: trained models, evaluation evidence and saved
        budget plans for this source. Files on your computer are not touched.
      </ConfirmDialog>
    </Panel>
  );
}

function Generator() {
  const { refresh, select } = useWorkspace();
  const [enabled, setEnabled] = useState<Platform[]>(PLATFORMS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<Manifest | null>(null);
  return (
    <form
      className="grid"
      style={{ gap: 14 }}
      onSubmit={async (e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        setBusy(true);
        setError("");
        setSaved(null);
        try {
          const m = await api<Manifest>(
            "/datasets/generate",
            post({
              name: String(f.get("name")),
              rows: Number(f.get("rows")),
              seed: Number(f.get("seed")),
              start_date: f.get("start_date"),
              end_date: f.get("end_date"),
              platforms: enabled,
            }),
          );
          await select(m.id);
          await refresh();
          setSaved(m);
        } catch (err) {
          setError(errorText(err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <Notice tone="warn">
        Simulated Pakistan-market campaigns with a spend-driven funnel, seasonality and diminishing returns. Results are labelled
        synthetic everywhere and never represent real ROAS.
      </Notice>
      <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: 0 }} className="grid">
        <div className="form-grid">
          <label className="field">
            Dataset name
            <input className="input" name="name" required maxLength={100} defaultValue="Pakistan campaign demo" />
          </label>
          <label className="field">
            Rows
            <select className="select" name="rows" defaultValue="10000">
              <option value="1000">1,000 · quick sample</option>
              <option value="10000">10,000 · standard demo</option>
            </select>
            <span className="hint">10K–10M academic inputs are generated in the Big Data lab.</span>
          </label>
          <label className="field">
            Seed
            <input className="input" name="seed" type="number" min={0} max={4294967295} required defaultValue={42} />
            <span className="hint">The same seed reproduces identical rows.</span>
          </label>
          <label className="field">
            Start
            <input className="input" name="start_date" type="date" required defaultValue="2026-01-01" />
          </label>
          <label className="field">
            End
            <input className="input" name="end_date" type="date" required defaultValue="2026-03-31" />
            <span className="hint">7–366 days.</span>
          </label>
        </div>
        <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field" style={{ marginBottom: 8 }}>
            Platforms
          </legend>
          <div className="btn-row">
            {PLATFORMS.map((p) => (
              <label key={p} className="check">
                <input
                  type="checkbox"
                  checked={enabled.includes(p)}
                  onChange={(e) => setEnabled(e.target.checked ? PLATFORMS.filter((x) => x === p || enabled.includes(x)) : enabled.filter((x) => x !== p))}
                />
                {p}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="btn-row">
          <button className="btn primary" type="submit" disabled={!enabled.length}>
            Generate & select
          </button>
          <a className="btn ghost" href="/api/v1/templates/campaign.csv" download>
            <Download size={15} /> Download a 100-row synthetic CSV template
          </a>
        </div>
      </fieldset>
      {busy && <Busy text="Generating rows on the backend…" />}
      {error && <Notice tone="error">{error}</Notice>}
      {saved && (
        <Notice tone="ok" title={`Saved and selected “${saved.name}”`}>
          {num(saved.rows)} rows · seed {saved.seed}.{" "}
          <Link href="/overview" style={{ fontWeight: 700 }}>
            Open the overview →
          </Link>
        </Notice>
      )}
    </form>
  );
}

const initialOptions: ImportOptions = {
  name: "Imported campaigns",
  mapping: {},
  default_platform: null,
  original_currency: "PKR",
  exchange_rate: null,
  date_format: "auto",
  date_granularity: "auto",
  conversion_definition: "unspecified",
  attribution_window: "unspecified",
  is_synthetic: false,
  exclude_invalid: false,
  drop_duplicates: true,
  confirmed: false,
};

function Importer() {
  const { refresh, select } = useWorkspace();
  const [profile, setProfile] = useState("generic");
  const [stage, setStage] = useState<Stage | null>(null);
  const [options, setOptions] = useState<ImportOptions>(initialOptions);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<Manifest | null>(null);
  const update = (change: Partial<ImportOptions>) => {
    setOptions((o) => ({ ...o, ...change, confirmed: false }));
    setReport(null);
  };

  async function upload(file?: File) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv") || file.size > 10 * 1024 * 1024) {
      setError("Choose a UTF-8 .csv file no larger than 10 MiB.");
      return;
    }
    setBusy("Reading and staging your CSV…");
    setError("");
    setReport(null);
    setSaved(null);
    try {
      if (stage) await api(`/imports/${stage.token}`, { method: "DELETE" }).catch(() => undefined);
      const s = await api<Stage>(`/imports/preview?${new URLSearchParams({ filename: file.name, profile })}`, {
        method: "POST",
        headers: { "Content-Type": "text/csv" },
        body: file,
      });
      const hint = (k: "conversion_definition" | "attribution_window") =>
        s.reporting_hints?.[k]?.status === "detected" ? s.reporting_hints[k].value || "unspecified" : "unspecified";
      setStage(s);
      setOptions({
        ...initialOptions,
        name: file.name.replace(/\.csv$/i, "").slice(0, 100),
        mapping: s.suggested_mapping,
        original_currency: s.detected_currencies.length === 1 ? s.detected_currencies[0] : "PKR",
        conversion_definition: hint("conversion_definition"),
        attribution_window: hint("attribution_window"),
      });
    } catch (e) {
      setStage(null);
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }

  async function discard() {
    if (stage) await api(`/imports/${stage.token}`, { method: "DELETE" }).catch(() => undefined);
    setStage(null);
    setReport(null);
    setOptions(initialOptions);
  }

  return (
    <div className="grid" style={{ gap: 14 }}>
      <Notice>
        CSV only · UTF-8 · up to 10 MiB / 100,000 rows · daily or weekly campaign observations. Only import data you are
        authorized to use. Unmapped personal fields are discarded before staging; staged previews expire after 24 hours.
      </Notice>
      <div className="form-grid">
        <label className="field">
          Export profile
          <select className="select" value={profile} disabled={!!busy || !!stage} onChange={(e) => setProfile(e.target.value)}>
            <option value="generic">Generic campaign CSV</option>
            <option value="meta">Meta Ads Manager</option>
            <option value="google">Google Ads</option>
            <option value="tiktok">TikTok Ads Manager</option>
          </select>
        </label>
        <label className="field">
          CSV file
          <input className="input" type="file" accept=".csv,text/csv" disabled={!!busy} onChange={(e) => void upload(e.target.files?.[0])} />
        </label>
      </div>
      {busy && <Busy text={busy} />}
      {error && <Notice tone="error">{error}</Notice>}
      {saved && (
        <Notice tone="ok" title={`Saved and selected “${saved.name}”`}>
          {num(saved.rows)} rows.{" "}
          <Link href="/overview" style={{ fontWeight: 700 }}>
            Open the overview →
          </Link>
        </Notice>
      )}
      {stage && (
        <>
          <Panel
            flat
            title={`1 · Preview “${stage.filename}”`}
            description={`${num(stage.row_count)} rows · ${stage.columns.length} columns · profile ${stage.profile}`}
            actions={
              <button className="btn sm ghost" type="button" onClick={() => void discard()}>
                <X size={14} /> Discard upload
              </button>
            }
          >
            {stage.warnings.map((w) => (
              <Notice key={w} tone="warn">
                {w}
              </Notice>
            ))}
            <details className="disclose" style={{ marginTop: 8 }}>
              <summary>First rows as uploaded</summary>
              <div style={{ marginTop: 10 }}>
                <RowsTable columns={stage.columns} rows={stage.preview} caption="Uploaded CSV preview" />
              </div>
            </details>
          </Panel>
          <Panel flat title="2 · Map columns" description="Suggestions come from header aliases and sample values. Ambiguous candidates need your choice.">
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Field</th>
                    <th scope="col">CSV column</th>
                    <th scope="col">Recognition</th>
                  </tr>
                </thead>
                <tbody>
                  {[...REQUIRED, ...EXTRA].map((field) => {
                    const detail = stage.mapping_details[field];
                    return (
                      <tr key={field}>
                        <th scope="row">
                          {field}
                          {EXTRA.includes(field) && <span className="faint"> (optional)</span>}
                        </th>
                        <td>
                          <label className="sr-only" htmlFor={`map-${field}`}>
                            Column for {field}
                          </label>
                          <select
                            id={`map-${field}`}
                            className="select"
                            style={{ minHeight: 34, minWidth: 180 }}
                            value={options.mapping[field] || ""}
                            onChange={(e) => update({ mapping: { ...options.mapping, [field]: e.target.value } })}
                          >
                            <option value="">Not in this file</option>
                            {stage.columns.map((c) => (
                              <option key={c} value={c}>
                                {c}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td style={{ whiteSpace: "normal", minWidth: 220 }} className="faint">
                          {detail ? (
                            <>
                              <span className={`badge ${detail.status === "automatic" ? "ok" : detail.status === "missing" ? "" : "amber"}`}>
                                {detail.status}
                              </span>{" "}
                              {detail.reason}
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel flat title="3 · Definitions, currency and policy">
            <div className="form-grid">
              <label className="field">
                Dataset name
                <input className="input" value={options.name} maxLength={100} onChange={(e) => update({ name: e.target.value })} />
              </label>
              <label className="field">
                Default platform
                <select
                  className="select"
                  value={options.default_platform || ""}
                  onChange={(e) => update({ default_platform: (e.target.value || null) as Platform | null })}
                >
                  <option value="">None · use mapped column</option>
                  {PLATFORMS.map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
                <span className="hint">Only when the whole file is one platform.</span>
              </label>
              <label className="field">
                Original currency
                <input
                  className="input"
                  value={options.original_currency}
                  maxLength={3}
                  onChange={(e) => {
                    const v = e.target.value.toUpperCase();
                    update({ original_currency: v, exchange_rate: v === "PKR" ? null : options.exchange_rate });
                  }}
                />
                {stage.detected_currencies.length > 0 && <span className="hint">Detected: {stage.detected_currencies.join(", ")}</span>}
              </label>
              {options.original_currency !== "PKR" && (
                <label className="field">
                  Verified PKR per 1 {options.original_currency}
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step="any"
                    value={options.exchange_rate ?? ""}
                    onChange={(e) => update({ exchange_rate: e.target.value ? Number(e.target.value) : null })}
                  />
                  <span className="hint">Required; no rate is ever assumed.</span>
                </label>
              )}
              <label className="field">
                Date format
                <select className="select" value={options.date_format} onChange={(e) => update({ date_format: e.target.value as ImportOptions["date_format"] })}>
                  <option value="auto">Detect (unambiguous only)</option>
                  <option value="%Y-%m-%d">YYYY-MM-DD</option>
                  <option value="%d/%m/%Y">DD/MM/YYYY</option>
                  <option value="%m/%d/%Y">MM/DD/YYYY</option>
                  <option value="%G-W%V">ISO week · 2026-W43</option>
                </select>
              </label>
              <label className="field">
                Reporting period
                <select
                  className="select"
                  value={options.date_granularity}
                  onChange={(e) => update({ date_granularity: e.target.value as ImportOptions["date_granularity"] })}
                >
                  <option value="auto">Detect</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </label>
              <label className="field">
                Conversion definition
                <input className="input" value={options.conversion_definition} maxLength={100} onChange={(e) => update({ conversion_definition: e.target.value })} />
                <span className="hint">{stage.reporting_hints?.conversion_definition?.evidence}</span>
              </label>
              <label className="field">
                Attribution window
                <input className="input" value={options.attribution_window} maxLength={100} onChange={(e) => update({ attribution_window: e.target.value })} />
                <span className="hint">{stage.reporting_hints?.attribution_window?.evidence}</span>
              </label>
              <label className="field">
                Data origin
                <select className="select" value={String(options.is_synthetic)} onChange={(e) => update({ is_synthetic: e.target.value === "true" })}>
                  <option value="false">Authorized advertiser export</option>
                  <option value="true">Synthetic / test fixture</option>
                </select>
              </label>
            </div>
            <div className="grid" style={{ gap: 8, marginTop: 14 }}>
              <label className="check">
                <input type="checkbox" checked={options.drop_duplicates} onChange={(e) => update({ drop_duplicates: e.target.checked })} />
                Remove exact duplicate rows
              </label>
              <label className="check">
                <input type="checkbox" checked={options.exclude_invalid} onChange={(e) => update({ exclude_invalid: e.target.checked })} />
                Exclude invalid rows (only after reviewing their count below)
              </label>
            </div>
            <div className="btn-row" style={{ marginTop: 14 }}>
              <button
                className="btn"
                type="button"
                disabled={!!busy || !options.name.trim()}
                onClick={async () => {
                  setBusy("Validating every mapped row…");
                  setError("");
                  try {
                    const r = await api<ValidationReport>(`/imports/${stage.token}/validate`, post(options));
                    setReport(r);
                  } catch (e) {
                    setError(errorText(e));
                  } finally {
                    setBusy("");
                  }
                }}
              >
                Validate mapping
              </button>
            </div>
          </Panel>
          {report && (
            <Panel flat title="4 · Validation report" description="Nothing has been saved yet.">
              <div className="kpis" style={{ marginBottom: 12 }}>
                {[
                  ["Input rows", report.input_rows],
                  ["Valid", report.valid_rows],
                  ["Invalid", report.invalid_rows],
                  ["Duplicates", report.duplicate_rows],
                  ["Excluded", report.excluded_rows],
                ].map(([k, v]) => (
                  <div key={k} className="kpi">
                    <div className="kpi-label">{k}</div>
                    <div className="kpi-value">{num(v as number)}</div>
                  </div>
                ))}
              </div>
              <p className="faint">
                Period {report.date_granularity} · revenue usable for planning: {report.data_ready_for_revenue ? "yes" : "no"} · coverage{" "}
                {Object.entries(report.coverage)
                  .map(([k, v]) => `${k} ${coverage(v)}`)
                  .join(" · ")}
              </p>
              {report.errors.length > 0 && (
                <Notice tone="error" title="Rows that need correction">
                  <ul>
                    {report.errors.map((e) => (
                      <li key={e.field + e.message}>
                        <strong>{e.field}</strong>: {e.message} ({num(e.count)} rows{e.rows.length ? `, e.g. ${e.rows.slice(0, 5).join(", ")}` : ""})
                      </li>
                    ))}
                  </ul>
                </Notice>
              )}
              {report.warnings.map((w) => (
                <Notice key={w} tone="warn">
                  {w}
                </Notice>
              ))}
              {report.preview.length > 0 && (
                <details className="disclose" style={{ margin: "10px 0" }}>
                  <summary>Normalized rows preview</summary>
                  <div style={{ marginTop: 10 }}>
                    <RowsTable columns={Object.keys(report.preview[0])} rows={report.preview} caption="Normalized preview" />
                  </div>
                </details>
              )}
              {report.can_import ? (
                <div className="grid" style={{ gap: 12, marginTop: 10 }}>
                  <label className="check">
                    <input type="checkbox" checked={options.confirmed} onChange={(e) => setOptions({ ...options, confirmed: e.target.checked })} />
                    I have permission to use this data and have reviewed its source, currency, mapping, reporting rules, duplicates and
                    exclusions.
                  </label>
                  <div className="btn-row">
                    <button
                      className="btn primary"
                      type="button"
                      disabled={!!busy || !options.confirmed}
                      onClick={async () => {
                        setBusy("Saving the validated dataset…");
                        setError("");
                        try {
                          const m = await api<Manifest>(`/imports/${stage.token}/commit`, post(options));
                          setStage(null);
                          setReport(null);
                          setOptions(initialOptions);
                          await select(m.id);
                          await refresh();
                          setSaved(m);
                        } catch (e) {
                          setError(errorText(e));
                        } finally {
                          setBusy("");
                        }
                      }}
                    >
                      <Check size={16} /> Confirm and save
                    </button>
                  </div>
                </div>
              ) : (
                <Notice tone="warn">This file cannot be imported as mapped. Correct the mapping or options above and validate again.</Notice>
              )}
            </Panel>
          )}
        </>
      )}
    </div>
  );
}

function StudioInner() {
  const params = useSearchParams();
  const { loading } = useWorkspace();
  const [mode, setMode] = useState<"generate" | "import">(params.get("mode") === "import" ? "import" : "generate");
  if (loading) return <LoadingPage label="Loading datasets" />;
  return (
    <>
      <PageHead eyebrow="Data studio" title="Campaign data & provenance">
        Create labelled synthetic history or bring an authorized campaign export. Every saved source keeps its origin, mapping,
        currency and coverage.
      </PageHead>
      <SavedDatasets />
      <Panel
        title="Add a campaign source"
        actions={
          <Segmented
            label="Source type"
            value={mode}
            onChange={setMode}
            options={[
              { value: "generate", label: "Synthetic demo" },
              { value: "import", label: "Upload CSV" },
            ]}
          />
        }
      >
        {mode === "generate" ? <Generator /> : (
          <>
            <div className="btn-row" style={{ marginBottom: 12 }}>
              <FileUp size={16} color="var(--teal)" aria-hidden="true" />
              <span className="faint">Preview → map → validate → confirm. You can discard at any step.</span>
            </div>
            <Importer />
          </>
        )}
      </Panel>
      <Panel flat title="Academic Big Data inputs (10K → 10M rows)">
        <p className="muted" style={{ marginTop: 0 }}>
          Large benchmark inputs are generated as chunked Parquet in a separate namespace. They never replace the selected campaign
          source or flow into the overview.
        </p>
        <Link className="btn" href="/lab">
          Open the Big Data lab
        </Link>
      </Panel>
    </>
  );
}

export function DataStudio() {
  return (
    <Suspense fallback={<LoadingPage label="Loading data studio" />}>
      <StudioInner />
    </Suspense>
  );
}
