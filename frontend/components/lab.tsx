"use client";

import { Download, Play, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, errorText, labTerminal, PLATFORMS, post, type Engine, type ExperimentConfig, type LabJob, type LabState } from "@/lib/api";
import { bytes, compact, dateTime, engineName, num, secs, shortId } from "@/lib/format";
import { ChartTable } from "./charts";
import { Busy, ConfirmDialog, Kpi, LoadingPage, Notice, PageHead, Panel } from "./ui";

const SCALES = [10_000, 100_000, 1_000_000, 10_000_000] as const;
const ENGINE_COLOR: Record<string, string> = { pandas: "var(--teal)", mapreduce: "var(--amber)", spark: "var(--peri)" };
const ENGINE_DASH: Record<string, string | undefined> = { pandas: undefined, mapreduce: "6 4", spark: "2 3" };

const initial: ExperimentConfig = {
  kind: "benchmark",
  rows: 10_000,
  seed: 42,
  start_date: "2026-01-01",
  end_date: "2026-03-31",
  platforms: PLATFORMS,
  chunk_rows: 50_000,
  engines: ["pandas", "mapreduce", "spark"],
  repeats: 3,
  workers: 2,
  memory_mib: 2048,
  dataset_id: null,
};

function ScaleChart({ jobs }: { jobs: LabJob[] }) {
  // Latest completed measurement per (scale, engine), seed-matched to the default experiment.
  const best: Record<number, Record<string, number>> = {};
  for (const j of [...jobs].reverse()) {
    if (j.status !== "completed" || j.config.kind !== "benchmark") continue;
    for (const r of j.results) {
      if (r.status === "completed" && r.median_seconds != null) {
        best[j.config.rows] = { ...(best[j.config.rows] || {}), [r.engine]: r.median_seconds };
      }
    }
  }
  const rows = SCALES.filter((s) => best[s]).map((s) => ({ name: compact(s), rows: s, ...best[s] }));
  if (!rows.length) return <p className="muted">No completed benchmarks yet. Run one above; only measured results are plotted.</p>;
  const engines = ["pandas", "mapreduce", "spark"].filter((e) => rows.some((r) => (r as Record<string, unknown>)[e] != null));
  return (
    <div>
      <div className="chart-box" role="img" aria-label="Median aggregation time by scale and engine, log scale">
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ left: 0, right: 16, top: 8 }}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="3 4" vertical={false} />
            <XAxis dataKey="name" stroke="var(--text-3)" fontSize={12} />
            <YAxis scale="log" domain={["auto", "auto"]} stroke="var(--text-3)" fontSize={12} tickFormatter={(v) => secs(v)} width={64} allowDataOverflow />
            <Tooltip
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <div className="tt">
                    <strong>{label} rows</strong>
                    {payload.map((p) => (
                      <div key={String(p.dataKey)} className="num">
                        {engineName(String(p.dataKey))}: {secs(Number(p.value))}
                      </div>
                    ))}
                  </div>
                ) : null
              }
            />
            <Legend formatter={(v) => engineName(v)} wrapperStyle={{ fontSize: 12 }} />
            {engines.map((e) => (
              <Line key={e} dataKey={e} stroke={ENGINE_COLOR[e]} strokeDasharray={ENGINE_DASH[e]} strokeWidth={2.5} dot={{ r: 4 }} connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="faint">
        Median of measured repeats (excludes engine setup), log scale. Single-machine local runs; not distributed-cluster claims.
      </p>
      <ChartTable
        columns={["Rows", ...engines.map(engineName)]}
        rows={rows.map((r) => [num(r.rows), ...engines.map((e) => secs((r as unknown as Record<string, number>)[e] ?? null))])}
      />
    </div>
  );
}

function JobDetail({ job: raw }: { job: LabJob }) {
  const done = labTerminal(raw.status);
  // Adapter guard: an engine left non-terminal inside a finished job exited early; never show it as running/timed.
  const job = done
    ? { ...raw, results: raw.results.map((r) => (["completed", "failed", "skipped", "cancelled", "unavailable"].includes(r.status) ? r : { ...r, status: "incomplete", message: "The engine process ended before publishing all repeats. Review its local log and re-run." })) }
    : raw;
  return (
    <Panel
      title={`Run ${shortId(job.id)} · ${num(job.config.rows)} rows`}
      description={`${job.config.kind} · seed ${job.config.seed} · ${job.config.repeats} repeats · ${job.config.workers} workers · started ${dateTime(job.created_at)}`}
      actions={
        done && job.config.kind === "benchmark" ? (
          <>
            <a className="btn sm" href={`/api/v1/lab/jobs/${job.id}/export?format=json`} download>
              <Download size={14} /> JSON
            </a>
            <a className="btn sm" href={`/api/v1/lab/jobs/${job.id}/export?format=csv`} download>
              <Download size={14} /> CSV
            </a>
          </>
        ) : undefined
      }
    >
      <Notice tone={job.status === "completed" ? "ok" : job.status === "failed" ? "error" : done ? "warn" : "info"} title={`${job.status} · ${job.stage}`}>
        {job.message}
        {!done && job.config.rows > 0 && (
          <div className="bar-track" style={{ marginTop: 8 }}>
            <div className="bar-fill" style={{ width: `${Math.min(100, (job.generated_rows / job.config.rows) * 100)}%`, background: "var(--teal)" }} />
          </div>
        )}
      </Notice>
      {job.dataset && (
        <p className="faint num">
          Input: {num(job.dataset.rows)} rows · {job.dataset.parts} Parquet parts · {bytes(job.dataset.bytes)} · sha256 {job.dataset.sha256.slice(0, 12)}…
          {job.generation_seconds != null && ` · generated in ${secs(job.generation_seconds)}`}
        </p>
      )}
      {job.results.length > 0 && (
        <div className="grid" style={{ gap: 14, marginTop: 10 }}>
          <div className="kpis">
            {job.results.map((r) => (
              <Kpi
                key={r.engine}
                label={engineName(r.engine)}
                value={r.status === "completed" ? secs(r.median_seconds) : r.status}
                na={r.status !== "completed"}
                sub={
                  r.status === "completed"
                    ? `${compact(r.median_rows_per_second)} rows/s · setup ${secs(r.setup_seconds)} · peak ${bytes(r.peak_tree_rss_bytes)}`
                    : r.message
                }
              />
            ))}
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Engine</th>
                  <th scope="col">Mode</th>
                  <th scope="col" className="r">
                    Repeat
                  </th>
                  <th scope="col" className="r">
                    Elapsed
                  </th>
                  <th scope="col" className="r">
                    Rows / s
                  </th>
                  <th scope="col">Parity with reference</th>
                </tr>
              </thead>
              <tbody>
                {job.results.flatMap((r) =>
                  r.runs.length
                    ? r.runs.map((run) => (
                        <tr key={`${r.engine}-${run.repeat}`}>
                          <th scope="row">{engineName(r.engine)}</th>
                          <td className="faint">{r.mode}</td>
                          <td className="r">{run.repeat}</td>
                          <td className="r">{secs(run.elapsed_seconds)}</td>
                          <td className="r">{compact(run.rows_per_second)}</td>
                          <td>{run.correct ? <span className="badge ok">matches</span> : <span className="badge critical">mismatch</span>}</td>
                        </tr>
                      ))
                    : [
                        <tr key={r.engine}>
                          <th scope="row">{engineName(r.engine)}</th>
                          <td colSpan={5} className="faint" style={{ whiteSpace: "normal" }}>
                            {r.status}: {r.message}
                          </td>
                        </tr>,
                      ],
                )}
              </tbody>
            </table>
          </div>
          {job.dataset?.reference && (
            <details className="disclose">
              <summary>Reference weighted totals (the answer every engine must reproduce)</summary>
              <div className="table-wrap" style={{ marginTop: 8 }}>
                <table className="data">
                  <thead>
                    <tr>
                      {["Platform", "Rows", "Spend", "Clicks", "Conversions", "Revenue", "ROAS"].map((h, i) => (
                        <th key={h} className={i ? "r" : ""} scope="col">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {job.dataset.reference.map((p) => (
                      <tr key={p.name}>
                        <th scope="row">{p.name}</th>
                        <td className="r">{num(p.rows)}</td>
                        <td className="r">{num(p.spend, 2)}</td>
                        <td className="r">{num(p.clicks)}</td>
                        <td className="r">{num(p.conversions)}</td>
                        <td className="r">{num(p.revenue, 2)}</td>
                        <td className="r">{p.roas == null ? "—" : p.roas.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </div>
      )}
    </Panel>
  );
}

export function BigDataLab() {
  const [state, setState] = useState<LabState | null>(null);
  const [cfg, setCfg] = useState<ExperimentConfig>(initial);
  const [selected, setSelected] = useState<LabJob | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const s = await api<LabState>("/lab");
    setState(s);
    setCfg((c) => ({ ...c, engines: c.engines.filter((e) => s.environment.engines.find((x) => x.id === e)?.available) }));
    return s;
  }, []);

  useEffect(() => {
    api<LabState>("/lab")
      .then((s) => {
        setState(s);
        setCfg((c) => ({ ...c, engines: c.engines.filter((e) => s.environment.engines.find((x) => x.id === e)?.available) }));
        setSelected((cur) => cur || s.jobs[0] || null);
      })
      .catch((e) => setError(errorText(e)));
  }, []);

  useEffect(() => {
    if (!selected || labTerminal(selected.status)) return;
    const t = setTimeout(async () => {
      try {
        const next = await api<LabJob>(`/lab/jobs/${selected.id}`);
        setSelected(next);
        if (labTerminal(next.status)) await load();
      } catch (e) {
        setError(errorText(e));
      }
    }, 1500);
    return () => clearTimeout(t);
  }, [selected, load]);

  if (!state && !error) return <LoadingPage label="Reading the local environment" />;
  if (!state) return <Notice tone="error">{error}</Notice>;
  const env = state.environment;
  const active = state.jobs.find((j) => !labTerminal(j.status)) || (selected && !labTerminal(selected.status) ? selected : null);
  const toggleEngine = (e: Engine) =>
    setCfg({ ...cfg, engines: cfg.engines.includes(e) ? cfg.engines.filter((x) => x !== e) : (["pandas", "mapreduce", "spark"] as Engine[]).filter((x) => x === e || cfg.engines.includes(x)) });
  return (
    <>
      <PageHead eyebrow="Big Data lab" title="Pandas vs MapReduce vs Spark">
        The same weighted per-platform aggregation runs on identical seeded Parquet inputs at 10K, 100K, 1M and 10M rows. Every
        repeat is checked against a reference answer before its timing counts.
      </PageHead>
      {env.hosted && (
        <Notice tone="warn" title="Run the lab locally">
          This hosted deployment cannot start Spark/JVM or detached benchmark workers, and 10M-row inputs exceed hosted storage
          limits. Clone the project and run <code>npm run dev</code> to execute real experiments; saved local results can be exported.
        </Notice>
      )}
      <div className="grid cols-main-side">
        <Panel title="Experiment setup">
          <form
            className="grid"
            style={{ gap: 14 }}
            onSubmit={async (e) => {
              e.preventDefault();
              setError("");
              setBusy(true);
              try {
                const job = await api<LabJob>("/lab/jobs", post(cfg));
                setSelected(job);
                await load();
              } catch (err) {
                setError(errorText(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="field" style={{ marginBottom: 8 }}>
                Scale
              </legend>
              <div className="segmented" role="radiogroup" aria-label="Rows">
                {SCALES.map((s) => (
                  <button key={s} type="button" role="radio" aria-checked={cfg.rows === s} data-checked={cfg.rows === s} onClick={() => setCfg({ ...cfg, rows: s })}>
                    {compact(s)}
                  </button>
                ))}
              </div>
              {cfg.rows === 10_000_000 && (
                <p className="faint" style={{ marginBottom: 0 }}>
                  10M rows writes roughly a few hundred MiB of Parquet and can take several minutes per engine. Run it deliberately, alone.
                </p>
              )}
            </fieldset>
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="field" style={{ marginBottom: 8 }}>
                Engines
              </legend>
              <div className="grid" style={{ gap: 8 }}>
                {env.engines.map((e) => (
                  <label key={e.id} className="check" style={{ opacity: e.available ? 1 : 0.65 }}>
                    <input type="checkbox" disabled={!e.available} checked={cfg.engines.includes(e.id)} onChange={() => toggleEngine(e.id)} />
                    <span>
                      <strong>{e.label}</strong> {e.available ? <span className="badge ok">available</span> : <span className="badge critical">unavailable</span>}
                      <span className="faint" style={{ display: "block" }}>
                        {e.reason}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="form-grid">
              <label className="field">
                Measured repeats
                <input className="input" type="number" min={3} max={7} value={cfg.repeats} onChange={(e) => setCfg({ ...cfg, repeats: Number(e.target.value) })} />
              </label>
              <label className="field">
                Workers
                <input className="input" type="number" min={1} max={4} value={cfg.workers} onChange={(e) => setCfg({ ...cfg, workers: Number(e.target.value) })} />
              </label>
              <label className="field">
                Seed
                <input className="input" type="number" min={0} value={cfg.seed} onChange={(e) => setCfg({ ...cfg, seed: Number(e.target.value) })} />
              </label>
              <label className="field">
                Chunk rows
                <select className="select" value={cfg.chunk_rows} onChange={(e) => setCfg({ ...cfg, chunk_rows: Number(e.target.value) as ExperimentConfig["chunk_rows"] })}>
                  {[10_000, 50_000, 100_000].map((c) => (
                    <option key={c} value={c}>
                      {num(c)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Job type
                <select className="select" value={cfg.kind} onChange={(e) => setCfg({ ...cfg, kind: e.target.value as ExperimentConfig["kind"] })}>
                  <option value="benchmark">Benchmark (reuses input)</option>
                  <option value="generate">Generate input only</option>
                </select>
              </label>
            </div>
            <div className="btn-row">
              <button className="btn primary" type="submit" disabled={busy || !!active || env.hosted || (cfg.kind === "benchmark" && !cfg.engines.length)}>
                <Play size={15} /> {cfg.kind === "benchmark" ? "Start benchmark" : "Generate input"}
              </button>
              {active && (
                <button
                  className="btn danger"
                  type="button"
                  disabled={active.cancel_requested}
                  onClick={async () => {
                    try {
                      setSelected(await api<LabJob>(`/lab/jobs/${active.id}/cancel`, post({})));
                    } catch (e) {
                      setError(errorText(e));
                    }
                  }}
                >
                  <Square size={14} /> Cancel run
                </button>
              )}
            </div>
            {active && <Busy text={`Run ${shortId(active.id)} is ${active.stage}. One job runs at a time.`} />}
            {error && <Notice tone="error">{error}</Notice>}
          </form>
        </Panel>
        <Panel title="Measured environment" description="Read from this machine at request time.">
          <dl className="dl">
            <dt>OS</dt>
            <dd>{env.os}</dd>
            <dt>CPU</dt>
            <dd>
              {env.cpu} · {env.physical_cpus ?? "?"} physical / {env.logical_cpus ?? "?"} logical
            </dd>
            <dt>RAM</dt>
            <dd className="num">
              {bytes(env.ram_available_bytes)} free of {bytes(env.ram_total_bytes)}
            </dd>
            <dt>Disk free</dt>
            <dd className="num">{bytes(env.disk_free_bytes)}</dd>
            <dt>Python</dt>
            <dd>{env.python}</dd>
            <dt>Java</dt>
            <dd>{env.java ? env.java.description : "Not found (Spark unavailable)"}</dd>
            <dt>Input format</dt>
            <dd>{env.input_format}</dd>
            {Object.entries(env.packages).map(([k, v]) => (
              <span key={k} style={{ display: "contents" }}>
                <dt>{k}</dt>
                <dd className="mono">{v ?? "not installed"}</dd>
              </span>
            ))}
          </dl>
        </Panel>
      </div>
      <Panel title="Scale comparison" description="Latest completed run per scale and engine.">
        <ScaleChart jobs={state.jobs} />
      </Panel>
      {selected && <JobDetail job={selected} />}
      <div className="grid cols-2">
        <Panel title="Run history">
          {state.jobs.length ? (
            <div className="table-wrap" style={{ maxHeight: 340 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Run</th>
                    <th scope="col" className="r">
                      Rows
                    </th>
                    <th scope="col">Status</th>
                    <th scope="col">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {state.jobs.map((j) => (
                    <tr key={j.id}>
                      <th scope="row">
                        <button className="sort-btn mono" type="button" onClick={() => setSelected(j)} style={{ textDecoration: "underline" }}>
                          {shortId(j.id)}
                        </button>
                      </th>
                      <td className="r">{compact(j.config.rows)}</td>
                      <td>
                        <span className={`badge ${j.status === "completed" ? "ok" : j.status === "failed" ? "critical" : ""}`}>{j.status}</span>
                      </td>
                      <td className="faint">{dateTime(j.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No runs yet.</p>
          )}
        </Panel>
        <Panel title="Lab input datasets" description="Seeded Parquet inputs, separate from campaign sources.">
          {state.datasets.length ? (
            <div className="grid" style={{ gap: 8 }}>
              {state.datasets.map((d) => (
                <div key={d.id} className="btn-row" style={{ justifyContent: "space-between", borderBottom: "1px solid var(--line)", paddingBottom: 8 }}>
                  <span className="num" style={{ fontSize: 13 }}>
                    <strong>{compact(d.rows)}</strong> rows · seed {d.config.seed} · {d.parts} parts · {bytes(d.bytes)}
                  </span>
                  <button className="btn sm danger" type="button" disabled={!!active} onClick={() => setDeleting(d.id)} aria-label={`Delete ${compact(d.rows)} row input`}>
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No inputs generated yet.</p>
          )}
        </Panel>
      </div>
      <Panel flat title="Method">
        <dl className="dl">
          {Object.entries(state.methodology).map(([k, v]) => (
            <span key={k} style={{ display: "contents" }}>
              <dt style={{ textTransform: "capitalize" }}>{k.replaceAll("_", " ")}</dt>
              <dd>{v}</dd>
            </span>
          ))}
        </dl>
      </Panel>
      <ConfirmDialog
        open={!!deleting}
        title="Delete this lab input?"
        confirmLabel="Delete input"
        onClose={() => setDeleting(null)}
        onConfirm={async () => {
          try {
            await api(`/lab/datasets/${deleting}`, { method: "DELETE" });
            setDeleting(null);
            await load();
          } catch (e) {
            setError(errorText(e));
            setDeleting(null);
          }
        }}
      >
        The Parquet files are removed. Saved benchmark reports remain, but re-running that scale regenerates the input.
      </ConfirmDialog>
    </>
  );
}
