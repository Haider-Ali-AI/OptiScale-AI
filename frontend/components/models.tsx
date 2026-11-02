"use client";

import { Download, Play, RefreshCw, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  errorText,
  isAbort,
  modelFinished,
  post,
  type Evaluation,
  type MLState,
  type ModelJob,
  type Readiness,
  type Score,
} from "@/lib/api";
import { dateTime, num, pct, pkr, shortId, today } from "@/lib/format";
import { SimpleBars } from "./charts";
import { Busy, Kpi, LoadingPage, NeedDataset, Notice, PageHead, Panel, PlatformLabel } from "./ui";
import { useWorkspace } from "./workspace";

const scoreRow = (label: string, model: Score, base: Score) => {
  const better = model.rmse < base.rmse;
  return (
    <tr key={label}>
      <th scope="row">{label}</th>
      <td className="r">{pkr(model.mae, 0)}</td>
      <td className="r">{pkr(base.mae, 0)}</td>
      <td className="r" style={{ color: better ? "var(--ok)" : "var(--critical)", fontWeight: 700 }}>
        {pkr(model.rmse, 0)}
      </td>
      <td className="r">{pkr(base.rmse, 0)}</td>
      <td className="r">{model.r2 == null ? "—" : model.r2.toFixed(3)}</td>
      <td className="r">{model.wape == null ? "—" : pct(model.wape * 100, 1)}</td>
      <td className="r">{num(model.rows)}</td>
    </tr>
  );
};

function ScoreTable({ test, validation }: { test: Evaluation; validation: Evaluation }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">Split</th>
            <th scope="col" className="r">
              MAE model
            </th>
            <th scope="col" className="r">
              MAE baseline
            </th>
            <th scope="col" className="r">
              RMSE model
            </th>
            <th scope="col" className="r">
              RMSE baseline
            </th>
            <th scope="col" className="r">
              R²
            </th>
            <th scope="col" className="r">
              WAPE
            </th>
            <th scope="col" className="r">
              Rows
            </th>
          </tr>
        </thead>
        <tbody>
          {scoreRow("Validation", validation.model, validation.baseline)}
          {scoreRow("Holdout test", test.model, test.baseline)}
        </tbody>
      </table>
    </div>
  );
}

function Timeline({ splits }: { splits: Record<string, { rows: number; start: string; end: string }> }) {
  const order = ["train", "validation", "test"].filter((k) => splits[k]);
  const total = order.reduce((s, k) => s + splits[k].rows, 0) || 1;
  const color: Record<string, string> = { train: "var(--peri)", validation: "var(--amber)", test: "var(--teal)" };
  return (
    <div>
      <div className="stack-bar" role="img" aria-label={order.map((k) => `${k} ${splits[k].start} to ${splits[k].end}`).join("; ")}>
        {order.map((k) => (
          <span key={k} style={{ width: `${(splits[k].rows / total) * 100}%`, background: color[k] }} />
        ))}
      </div>
      <div className="grid cols-3" style={{ marginTop: 10, gap: 10 }}>
        {order.map((k) => (
          <div key={k} style={{ fontSize: 13 }}>
            <strong style={{ textTransform: "capitalize", color: color[k] }}>{k === "test" ? "holdout test" : k}</strong>
            <div className="num faint">
              {splits[k].start} → {splits[k].end}
            </div>
            <div className="num">{num(splits[k].rows)} rows</div>
          </div>
        ))}
      </div>
      <p className="faint">Chronological: earlier complete dates train, the middle selects settings, later dates are a sealed holdout.</p>
    </div>
  );
}

function JobResult({ job, onChanged }: { job: ModelJob; onChanged: () => void }) {
  const r = job.result;
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [reeval, setReeval] = useState<Evaluation["model"] | null>(null);
  if (!r)
    return (
      <Notice tone={job.status === "failed" ? "error" : "info"} title={`Job ${job.status}`}>
        {job.message}
      </Notice>
    );
  const accepted = r.acceptance.eligible;
  const improvement = r.test.baseline.rmse > 0 ? (1 - r.test.model.rmse / r.test.baseline.rmse) * 100 : null;
  return (
    <div className="grid">
      <div className={`notice ${accepted ? "ok" : "warn"}`} role="status">
        <div>
          <strong>{accepted ? "Accepted: model can feed budget planning" : "Rejected: model must not be used for planning"}</strong>
          <div className="faint">{r.acceptance.policy}</div>
          {r.acceptance.reasons.length > 0 && (
            <ul>
              {r.acceptance.reasons.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="kpis">
        <Kpi label="Algorithm" value={r.algorithm} sub={r.fallback_reason || `target: ${r.target}`} />
        <Kpi label="Holdout RMSE" value={pkr(r.test.model.rmse, 0)} sub={`baseline ${pkr(r.test.baseline.rmse, 0)}`} />
        <Kpi label="RMSE vs baseline" value={improvement == null ? "—" : `${improvement >= 0 ? "−" : "+"}${Math.abs(improvement).toFixed(1)}%`} sub="lower error is better" />
        <Kpi label="Holdout R²" value={r.test.model.r2 == null ? "—" : r.test.model.r2.toFixed(3)} />
        <Kpi label="Holdout WAPE" value={r.test.model.wape == null ? "—" : pct(r.test.model.wape * 100, 1)} />
        <Kpi label="Fit time" value={`${r.elapsed_seconds.toFixed(1)} s`} sub={r.grain} />
      </div>
      <Panel title="Model vs train-only baseline" description="Errors are in PKR of attributed revenue per observation.">
        <ScoreTable test={r.test} validation={r.validation} />
      </Panel>
      <div className="grid cols-2">
        <Panel title="Chronological split">
          <Timeline splits={r.splits} />
          <dl className="dl" style={{ marginTop: 10 }}>
            <dt>Eligible rows</dt>
            <dd className="num">
              {num(r.coverage.eligible_rows)} of {num(r.coverage.input_rows)}
            </dd>
            <dt>Maturity cutoff</dt>
            <dd className="num">
              {r.coverage.maturity_cutoff} (lag {r.coverage.label_lag_days} d)
            </dd>
          </dl>
        </Panel>
        <Panel title="Per-platform holdout error">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Platform</th>
                  <th scope="col" className="r">
                    RMSE model
                  </th>
                  <th scope="col" className="r">
                    RMSE baseline
                  </th>
                  <th scope="col" className="r">
                    Rows
                  </th>
                </tr>
              </thead>
              <tbody>
                {r.test.platforms.map((p) => (
                  <tr key={p.platform}>
                    <th scope="row">
                      <PlatformLabel name={p.platform} />
                    </th>
                    <td className="r" style={{ color: p.model.rmse <= p.baseline.rmse * 1.1 ? undefined : "var(--critical)" }}>
                      {pkr(p.model.rmse, 0)}
                    </td>
                    <td className="r">{pkr(p.baseline.rmse, 0)}</td>
                    <td className="r">{num(p.model.rows)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
      <div className="grid cols-2">
        <Panel title="Feature importance (top 10)" description="XGBoost gain share. Outcomes and simulator truth are excluded from features.">
          <SimpleBars
            label="Feature importance"
            data={r.feature_importance.slice(0, 10).map((f) => ({ name: f.feature, value: f.importance }))}
            fmt={(v) => v.toFixed(3)}
          />
        </Panel>
        <Panel title="Provenance & versions">
          <dl className="dl">
            <dt>Model id</dt>
            <dd className="mono">{job.id}</dd>
            <dt>Trained</dt>
            <dd>{dateTime(job.completed_at)}</dd>
            <dt>As-of / seed</dt>
            <dd className="num">
              {job.config.as_of_date} · seed {job.config.seed}
            </dd>
            <dt>Input checksum</dt>
            <dd className="mono">{job.input_sha256.slice(0, 16)}…</dd>
            {Object.entries(r.versions).map(([k, v]) => (
              <span key={k} style={{ display: "contents" }}>
                <dt>{k}</dt>
                <dd className="mono">{v}</dd>
              </span>
            ))}
          </dl>
          <p className="faint">{r.uncertainty}</p>
          <p className="faint">{r.recommendations_reason}</p>
        </Panel>
      </div>
      {r.limitations.length > 0 && (
        <Panel flat title="Limitations">
          <ul className="muted" style={{ margin: 0, fontSize: 14 }}>
            {r.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </Panel>
      )}
      <div className="btn-row">
        <button
          className="btn"
          type="button"
          disabled={!!busy}
          onClick={async () => {
            setBusy("Reloading the verified artifact and re-measuring the sealed holdout…");
            setError("");
            try {
              const res = await api<{ notice: string; test: Evaluation }>(`/ml/models/${job.id}/evaluate`, post({}));
              setNote(res.notice);
              setReeval(res.test.model);
              onChanged();
            } catch (e) {
              setError(errorText(e));
            } finally {
              setBusy("");
            }
          }}
        >
          <RefreshCw size={15} /> Evaluate saved model
        </button>
        <a className="btn" href={`/api/v1/ml/jobs/${job.id}/export`} download>
          <Download size={15} /> Export evaluation JSON
        </a>
      </div>
      {busy && <Busy text={busy} />}
      {error && <Notice tone="error">{error}</Notice>}
      {note && reeval && (
        <Notice tone="ok" title={note}>
          Re-measured holdout RMSE {pkr(reeval.rmse, 0)} · MAE {pkr(reeval.mae, 0)} · {num(reeval.rows)} rows
          {Math.abs(reeval.rmse - r.test.model.rmse) < 1e-6 ? " (identical to the stored result)." : " (differs from the stored result; investigate)."}
        </Notice>
      )}
    </div>
  );
}

export function ModelStudio() {
  const { dataset, refresh, loading: wsLoading } = useWorkspace();
  const [ml, setMl] = useState<MLState | null>(null);
  const [cfg, setCfg] = useState({ seed: 42, as_of_date: today(), label_lag_days: 7 });
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [job, setJob] = useState<ModelJob | null>(null);
  const [error, setError] = useState("");
  const [answers, setAnswers] = useState({ conversion_definition: "", attribution_window: "", confirmed: false });
  const poll = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    const s = await api<MLState>("/ml");
    setMl(s);
    return s;
  }, []);

  useEffect(() => {
    if (!dataset) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCfg((c) => ({ ...c, label_lag_days: dataset.is_synthetic ? 0 : 7 }));
    load()
      .then((s) => setJob(s.active_job && s.active_job.config.dataset_id === dataset.id ? s.active_job : s.jobs[0] || null))
      .catch((e) => setError(errorText(e)));
  }, [dataset, load]);

  useEffect(() => {
    if (!dataset) return;
    const c = new AbortController();
    const t = setTimeout(() => {
      api<Readiness>("/ml/readiness", { ...post({ dataset_id: dataset.id, ...cfg }), signal: c.signal })
        .then(setReadiness)
        .catch((e) => !isAbort(e) && setReadiness({ ready: false, reasons: [errorText(e)] }));
    }, 300);
    return () => {
      clearTimeout(t);
      c.abort();
    };
  }, [dataset, cfg]);

  // Poll an active job until it reaches a terminal status.
  useEffect(() => {
    if (!job || modelFinished(job.status)) return;
    poll.current = setTimeout(async () => {
      try {
        const next = await api<ModelJob>(`/ml/jobs/${job.id}`);
        setJob(next);
        if (modelFinished(next.status)) {
          await load();
          await refresh();
        }
      } catch (e) {
        setError(errorText(e));
      }
    }, 1500);
    return () => {
      if (poll.current) clearTimeout(poll.current);
    };
  }, [job, load, refresh]);

  if (wsLoading) return <LoadingPage label="Loading workspace" />;
  if (!dataset)
    return (
      <>
        <PageHead eyebrow="ML validation studio" title="Train and validate a revenue model" />
        <NeedDataset />
      </>
    );
  const running = !!job && !modelFinished(job.status);
  const setup = readiness?.reporting_setup;
  return (
    <>
      <PageHead eyebrow="ML validation studio" title="Revenue model validation">
        A local XGBoost regressor predicts attributed revenue from spend and audience context. It is only used for planning if it
        beats a train-only baseline on both validation and the sealed holdout.
      </PageHead>
      <div className="grid cols-main-side">
        <Panel title="Training controls">
          <form
            className="grid"
            style={{ gap: 14 }}
            onSubmit={async (e) => {
              e.preventDefault();
              setError("");
              try {
                setJob(await api<ModelJob>("/ml/jobs", post({ dataset_id: dataset.id, ...cfg })));
              } catch (err) {
                setError(errorText(err));
              }
            }}
          >
            <div className="form-grid">
              <label className="field">
                Label as-of date
                <input className="input" type="date" value={cfg.as_of_date} onChange={(e) => setCfg({ ...cfg, as_of_date: e.target.value })} />
                <span className="hint">Use 2026-10-29 to reproduce the documented academic demo.</span>
              </label>
              <label className="field">
                Label maturity lag (days)
                <input className="input" type="number" min={0} max={90} value={cfg.label_lag_days} onChange={(e) => setCfg({ ...cfg, label_lag_days: Number(e.target.value) })} />
              </label>
              <label className="field">
                Seed
                <input className="input" type="number" min={0} value={cfg.seed} onChange={(e) => setCfg({ ...cfg, seed: Number(e.target.value) })} />
              </label>
            </div>
            {readiness && (
              <Notice tone={readiness.ready ? "ok" : "warn"} title={readiness.ready ? "Ready to train" : "Not ready"}>
                {readiness.reasons.length > 0 && (
                  <ul>
                    {readiness.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                )}
                {readiness.splits && (
                  <span className="faint num">
                    Train {num(readiness.splits.train?.rows)} · validation {num(readiness.splits.validation?.rows)} · holdout{" "}
                    {num(readiness.splits.test?.rows)} rows
                  </span>
                )}
              </Notice>
            )}
            <div className="btn-row">
              <button className="btn primary" type="submit" disabled={running || !readiness?.ready}>
                <Play size={15} /> Train revenue model
              </button>
              {running && (
                <button
                  className="btn danger"
                  type="button"
                  disabled={job.cancel_requested}
                  onClick={async () => {
                    try {
                      setJob(await api<ModelJob>(`/ml/jobs/${job.id}/cancel`, post({})));
                    } catch (e) {
                      setError(errorText(e));
                    }
                  }}
                >
                  <Square size={14} /> Cancel
                </button>
              )}
            </div>
            {running && <Busy text={`${job.stage}: ${job.message || "working…"}`} />}
            {error && <Notice tone="error">{error}</Notice>}
          </form>
        </Panel>
        <Panel title="Model history" description="Models trained on the selected source.">
          {ml?.jobs.length ? (
            <div className="grid" style={{ gap: 8 }}>
              {ml.jobs.slice(0, 8).map((j) => (
                <button
                  key={j.id}
                  type="button"
                  className="btn"
                  style={{ justifyContent: "space-between", borderColor: job?.id === j.id ? "var(--teal)" : undefined }}
                  onClick={() => setJob(j)}
                >
                  <span className="mono">{shortId(j.id)}</span>
                  <span className="faint">{j.config.as_of_date}</span>
                  <span className={`badge ${j.result?.acceptance.eligible ? "ok" : j.status === "succeeded" ? "amber" : "critical"}`}>
                    {j.status === "succeeded" ? (j.result?.acceptance.eligible ? "accepted" : "rejected") : j.status}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="muted">No models yet for this source.</p>
          )}
          {ml?.versions && (
            <p className="faint" style={{ marginBottom: 0 }}>
              Runtime: {Object.entries(ml.versions).map(([k, v]) => `${k} ${v ?? "missing"}`).join(" · ")}
            </p>
          )}
        </Panel>
      </div>
      {setup?.needs_answers && (
        <Panel title="Two reporting questions before training" description="Missing reporting rules are never guessed. Your answers create a new source-linked version.">
          <div className="form-grid">
            <label className="field">
              What counts as a conversion?
              <input className="input" value={answers.conversion_definition} placeholder="e.g. purchases" onChange={(e) => setAnswers({ ...answers, conversion_definition: e.target.value })} />
              <span className="hint">{setup.fields.conversion_definition?.evidence}</span>
            </label>
            <label className="field">
              Attribution window
              <input className="input" value={answers.attribution_window} placeholder="e.g. 7-day click, 1-day view" onChange={(e) => setAnswers({ ...answers, attribution_window: e.target.value })} />
              <span className="hint">{setup.fields.attribution_window?.evidence}</span>
            </label>
          </div>
          <label className="check" style={{ marginTop: 10 }}>
            <input type="checkbox" checked={answers.confirmed} onChange={(e) => setAnswers({ ...answers, confirmed: e.target.checked })} />
            These match how the report was exported.
          </label>
          <button
            className="btn"
            type="button"
            style={{ marginTop: 10 }}
            disabled={!answers.confirmed || !answers.conversion_definition.trim() || !answers.attribution_window.trim()}
            onClick={async () => {
              try {
                await api(`/datasets/${dataset.id}/reporting-setup`, post(answers));
                await refresh();
              } catch (e) {
                setError(errorText(e));
              }
            }}
          >
            Save my answers
          </button>
        </Panel>
      )}
      {job && modelFinished(job.status) && <JobResult key={job.id} job={job} onChanged={() => void load()} />}
    </>
  );
}
