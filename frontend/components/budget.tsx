"use client";

import { CheckCircle2, Download, History, Scale } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  api,
  errorText,
  isAbort,
  post,
  type Manifest,
  type OptimizerState,
  type Plan,
  type PlanConfig,
  type PlanMethod,
  type PlatformLimit,
} from "@/lib/api";
import { dateTime, NA, pkr, ratio, shortId, today } from "@/lib/format";
import { AllocationBar, CurveChart } from "./charts";
import { Busy, Kpi, LoadingPage, NeedDataset, Notice, PageHead, Panel, PlatformLabel } from "./ui";
import { useWorkspace } from "./workspace";

const METHODS: { value: PlanMethod; label: string; help: string }[] = [
  { value: "auto", label: "Automatic", help: "Accepted source-matched model → screened historical baseline → allocation only." },
  { value: "model", label: "Accepted ML model", help: "XGBoost predictions with conservative concave response curves." },
  { value: "baseline", label: "Screened statistical baseline", help: "Evaluates a historical baseline first; forecasts only if it passes." },
  { value: "historical", label: "Historical baseline (no ML)", help: "Explicit historical-rule heuristic; still evaluated." },
  { value: "evidence", label: "Allocation only", help: "Splits the budget within your limits without any revenue forecast." },
];

/** Integer paisa so the client-side verification sum is exact. */
const paisa = (v: number) => Math.round(v * 100);

function issuesFor(config: PlanConfig, state: OptimizerState) {
  const issues: string[] = [];
  if (!(config.budget > 0) || config.budget > 100_000_000) issues.push("Enter a budget between PKR 0.01 and 100,000,000.");
  else if (Math.abs(config.budget * 100 - Math.round(config.budget * 100)) > 1e-6) issues.push("Use at most two decimal places (paisa).");
  if (!config.platforms.length) issues.push("Enable at least one platform.");
  if (config.platforms.some((p) => !Number.isInteger(p.min_percent) || !Number.isInteger(p.max_percent) || p.min_percent < 0 || p.max_percent > 100 || p.min_percent > p.max_percent))
    issues.push("Use whole percentages 0–100, with each maximum at least its minimum.");
  if (config.platforms.reduce((s, p) => s + p.min_percent, 0) > 100) issues.push("Minimum shares cannot total more than 100%.");
  if (config.platforms.reduce((s, p) => s + p.max_percent, 0) < 100) issues.push("Maximum shares must cover at least 100% of the budget.");
  if (config.platforms.some((p) => p.max_amount != null && (p.min_amount ?? 0) > p.max_amount)) issues.push("A platform's minimum PKR amount exceeds its maximum.");
  const model = state.models.find((m) => m.id === config.model_id);
  if (config.method === "model" && !model?.eligible) issues.push("Choose an accepted model (train one in the ML validation studio).");
  const boundary = config.method === "model" && model ? [model.as_of_date, model.test_end].sort().at(-1)! : config.as_of_date;
  if (!config.start_date || config.start_date <= boundary) issues.push(`Choose a start date after ${boundary} (label as-of / model history).`);
  if (!Number.isInteger(config.horizon_days) || config.horizon_days < 1 || config.horizon_days > 30) issues.push("Choose a horizon of 1–30 days.");
  return issues;
}

function defaultConfig(dataset: Manifest, state: OptimizerState): PlanConfig {
  return {
    dataset_id: dataset.id,
    method: "auto",
    model_id: null,
    budget: 0,
    step: null,
    start_date: state.suggested_start,
    horizon_days: 7,
    as_of_date: today(),
    label_lag_days: dataset.is_synthetic ? 0 : 7,
    platforms: (dataset.options.platform || []).map((platform) => ({ platform, min_percent: 0, max_percent: 100 }) as PlatformLimit),
  };
}

function PlanView({ plan, stale }: { plan: Plan; stale: boolean }) {
  const sum = plan.allocations.reduce((s, a) => s + paisa(a.budget), 0);
  const exact = sum === paisa(plan.totals.budget);
  const forecast = plan.totals.estimated_revenue != null && !stale;
  return (
    <div className="grid">
      {stale && (
        <Notice tone="warn" title="Inputs changed since this plan was generated">
          Estimates are hidden until you generate again. The saved plan itself is unchanged.
        </Notice>
      )}
      <div className="kpis">
        <Kpi label="Budget allocated" value={pkr(plan.totals.budget)} />
        <Kpi label="Method used" value={plan.method_label} />
        <Kpi
          label="Estimated attributed revenue"
          value={forecast ? pkr(plan.totals.estimated_revenue) : NA}
          na={!forecast}
          sub={forecast ? "Planning estimate, not a guarantee" : plan.forecast_status === "unavailable" ? "Forecast not supported" : undefined}
        />
        <Kpi label="Estimated ROAS" value={forecast ? ratio(plan.totals.estimated_roas) : NA} na={!forecast} />
      </div>
      <div className={`notice ${exact ? "ok" : "error"}`} role="status">
        <CheckCircle2 size={17} color={exact ? "var(--ok)" : "var(--critical)"} aria-hidden="true" />
        <span>
          Exact-total check: platform amounts sum to <strong className="num">{pkr(sum / 100)}</strong>{" "}
          {exact ? "— equal to the requested budget to the last paisa." : "— does NOT match the budget. Do not use this plan."}
        </span>
      </div>
      <Panel title="Recommended allocation" description={`${plan.config.start_date} → ${plan.planning_end} · ${plan.config.horizon_days}-day horizon · saved ${dateTime(plan.created_at)}`}>
        <AllocationBar items={plan.allocations} />
        <div className="table-wrap" style={{ marginTop: 14 }}>
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Platform</th>
                <th scope="col" className="r">
                  Amount
                </th>
                <th scope="col" className="r">
                  Share
                </th>
                <th scope="col" className="r">
                  Limits applied
                </th>
                <th scope="col" className="r">
                  Est. revenue
                </th>
                <th scope="col">Why</th>
              </tr>
            </thead>
            <tbody>
              {plan.allocations.map((a) => (
                <tr key={a.platform}>
                  <th scope="row">
                    <PlatformLabel name={a.platform} />
                  </th>
                  <td className="r" style={{ fontWeight: 750 }}>
                    {pkr(a.budget)}
                  </td>
                  <td className="r">{a.share_percent.toFixed(2)}%</td>
                  <td className="r faint">
                    {pkr(a.effective_min, 0)} – {pkr(a.effective_max, 0)}
                  </td>
                  <td className="r">{forecast && a.estimated_revenue != null ? pkr(a.estimated_revenue) : NA}</td>
                  <td style={{ whiteSpace: "normal", minWidth: 260 }} className="muted">
                    {a.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="grid cols-2">
        <Panel title="Evidence & caveats">
          <dl className="dl">
            <dt>Forecast status</dt>
            <dd>{plan.forecast_status || "—"}</dd>
            <dt>Objective</dt>
            <dd>{plan.objective}</dd>
            <dt>Training period</dt>
            <dd className="num">
              {plan.training_period?.start} → {plan.training_period?.end}
            </dd>
            {plan.model_id && (
              <>
                <dt>Model</dt>
                <dd className="mono">{shortId(plan.model_id)}</dd>
              </>
            )}
            <dt>Source checksum</dt>
            <dd className="mono">{plan.source_sha256.slice(0, 16)}…</dd>
            <dt>Synthetic</dt>
            <dd>{plan.is_synthetic ? "Yes: simulated outcomes only" : "No"}</dd>
          </dl>
          {!!plan.forecast_reasons?.length && (
            <Notice tone="warn" title="Why revenue may be withheld">
              <ul>
                {plan.forecast_reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </Notice>
          )}
          {plan.baseline_assessment && (
            <Notice tone={plan.baseline_assessment.eligible ? "ok" : "warn"} title={`Baseline screen: ${plan.baseline_assessment.eligible ? "passed" : "not passed"}`}>
              <ul>
                {plan.baseline_assessment.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </Notice>
          )}
          <p className="faint">{plan.uncertainty}</p>
          <p className="faint">{plan.notice}</p>
          {plan.limitations.length > 0 && (
            <details className="disclose">
              <summary>Limitations ({plan.limitations.length})</summary>
              <ul className="muted" style={{ fontSize: 13 }}>
                {plan.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </details>
          )}
        </Panel>
        <Panel title="Same-budget comparisons" description="Alternative splits scored with the same evidence.">
          {plan.comparisons.length ? (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Scenario</th>
                    <th scope="col" className="r">
                      Est. revenue
                    </th>
                    <th scope="col" className="r">
                      Recommended plan gains
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {plan.comparisons.map((c) => (
                    <tr key={c.name}>
                      <th scope="row" style={{ whiteSpace: "normal" }}>
                        {c.name}
                      </th>
                      <td className="r">{forecast && c.estimated_revenue != null ? pkr(c.estimated_revenue) : NA}</td>
                      <td className="r">{forecast && c.estimated_revenue != null ? pkr(c.estimated_difference) : NA}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No comparison scenarios were returned for this method.</p>
          )}
          {forecast && plan.curves.length > 0 && (
            <>
              <h3 style={{ fontSize: 14, margin: "16px 0 4px" }}>Planning response curves</h3>
              <CurveChart curves={plan.curves} />
              <p className="faint">Adjusted (concave, monotone) curves impose diminishing returns; they are a planning assumption, not a new fit.</p>
            </>
          )}
        </Panel>
      </div>
      <div className="btn-row no-print">
        <a className="btn" href={`/api/v1/optimizer/plans/${plan.id}/export?format=csv`} download>
          <Download size={15} /> Export CSV
        </a>
        <a className="btn" href={`/api/v1/optimizer/plans/${plan.id}/export?format=json`} download>
          <Download size={15} /> Export JSON
        </a>
        <button className="btn ghost" type="button" onClick={() => window.print()}>
          Print report
        </button>
      </div>
    </div>
  );
}

function ScenarioReview({ state }: { state: OptimizerState }) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [plans, setPlans] = useState<[Plan, Plan] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!a || !b || a === b) return;
    const c = new AbortController();
    Promise.all([api<Plan>(`/optimizer/plans/${a}`, { signal: c.signal }), api<Plan>(`/optimizer/plans/${b}`, { signal: c.signal })])
      .then((p) => {
        setPlans(p as [Plan, Plan]);
        setError("");
      })
      .catch((e) => !isAbort(e) && setError(errorText(e)));
    return () => c.abort();
  }, [a, b]);
  if (state.plans.length < 2) return null;
  const label = (id: string) => {
    const p = state.plans.find((x) => x.id === id);
    return p ? `${pkr(p.totals.budget, 0)} · ${p.method_label} · ${dateTime(p.created_at)}` : id;
  };
  const shown = plans && plans[0].id === a && plans[1].id === b ? plans : null;
  const platforms = shown ? Array.from(new Set([...shown[0].allocations, ...shown[1].allocations].map((x) => x.platform))) : [];
  return (
    <Panel
      title={
        <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
          <Scale size={18} color="var(--peri)" aria-hidden="true" /> Budget scenario review
        </span>
      }
      description="Compare two saved plans. Allocation differences are exact; revenue differences only appear when both plans have supported forecasts."
    >
      <div className="form-grid">
        {[
          ["Scenario A", a, setA],
          ["Scenario B", b, setB],
        ].map(([l, v, set]) => (
          <label className="field" key={l as string}>
            {l as string}
            <select className="select" value={v as string} onChange={(e) => (set as (x: string) => void)(e.target.value)}>
              <option value="">Choose a saved plan</option>
              {state.plans.map((p) => (
                <option key={p.id} value={p.id}>
                  {label(p.id)}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {error && <Notice tone="error">{error}</Notice>}
      {a && a === b && <p className="faint">Choose two different plans.</p>}
      {shown && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Platform</th>
                <th scope="col" className="r">
                  A amount
                </th>
                <th scope="col" className="r">
                  B amount
                </th>
                <th scope="col" className="r">
                  B − A
                </th>
              </tr>
            </thead>
            <tbody>
              {platforms.map((p) => {
                const x = shown[0].allocations.find((q) => q.platform === p)?.budget ?? 0;
                const y = shown[1].allocations.find((q) => q.platform === p)?.budget ?? 0;
                return (
                  <tr key={p}>
                    <th scope="row">
                      <PlatformLabel name={p} />
                    </th>
                    <td className="r">{pkr(x)}</td>
                    <td className="r">{pkr(y)}</td>
                    <td className="r">{pkr((paisa(y) - paisa(x)) / 100)}</td>
                  </tr>
                );
              })}
              <tr>
                <th scope="row">Estimated revenue</th>
                <td className="r">{pkr(shown[0].totals.estimated_revenue)}</td>
                <td className="r">{pkr(shown[1].totals.estimated_revenue)}</td>
                <td className="r">
                  {shown[0].totals.estimated_revenue != null && shown[1].totals.estimated_revenue != null && shown[0].config.budget === shown[1].config.budget
                    ? pkr(shown[1].totals.estimated_revenue - shown[0].totals.estimated_revenue)
                    : NA}
                </td>
              </tr>
            </tbody>
          </table>
          {shown[0].config.budget !== shown[1].config.budget && (
            <p className="faint" style={{ padding: "0 12px" }}>
              Budgets differ, so the revenue difference is not a like-for-like comparison and is withheld.
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}

export function BudgetStudio() {
  const { dataset, loading: wsLoading } = useWorkspace();
  const [state, setState] = useState<OptimizerState | null>(null);
  const [config, setConfig] = useState<PlanConfig | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [budgetText, setBudgetText] = useState("");

  useEffect(() => {
    if (!dataset) return;
    const c = new AbortController();
    api<OptimizerState>("/optimizer", { signal: c.signal })
      .then(async (s) => {
        if (s.dataset_id !== dataset.id) throw new Error("The selected dataset changed. Refresh the page.");
        setState(s);
        setLoadError("");
        if (s.plans.length) {
          const latest = await api<Plan>(`/optimizer/plans/${s.plans[0].id}`, { signal: c.signal });
          setPlan(latest);
          setConfig(latest.config);
          setBudgetText(String(latest.config.budget));
        } else {
          setPlan(null);
          setConfig(defaultConfig(dataset, s));
          setBudgetText("");
        }
      })
      .catch((e) => !isAbort(e) && setLoadError(errorText(e)));
    return () => c.abort();
  }, [dataset]);

  const issues = useMemo(() => (config && state ? issuesFor(config, state) : []), [config, state]);
  if (wsLoading) return <LoadingPage label="Loading workspace" />;
  if (!dataset)
    return (
      <>
        <PageHead eyebrow="Budget decision studio" title="Where should the next budget go?" />
        <NeedDataset />
      </>
    );
  if (loadError) return <Notice tone="error">{loadError}</Notice>;
  if (!state || !config) return <LoadingPage label="Loading planning options" />;
  const stale = !!plan && JSON.stringify(config) !== JSON.stringify(plan.config);
  const update = (change: Partial<PlanConfig>) => {
    setConfig({ ...config, ...change });
    setError("");
  };
  const setLimit = (platform: string, change: Partial<PlatformLimit>) =>
    update({ platforms: config.platforms.map((p) => (p.platform === platform ? { ...p, ...change } : p)) });
  const accepted = state.models.filter((m) => m.eligible);

  return (
    <>
      <PageHead eyebrow="Budget decision studio" title="Plan an advisory budget">
        Enter the amount you actually have. The recommendation sums exactly to it, respects every limit you set and states which
        evidence produced it. Nothing here changes live ad spending.
      </PageHead>
      {!dataset.data_ready_for_revenue && (
        <Notice tone="warn">This source lacks usable revenue, so only allocation-only plans can be produced.</Notice>
      )}
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (issues.length || busy) return;
          setBusy("Computing exact allocation on the backend…");
          setError("");
          try {
            const result = await api<Plan>("/optimizer/plans", post(config));
            setPlan(result);
            setConfig(result.config);
            setState(await api<OptimizerState>("/optimizer"));
          } catch (err) {
            setError(errorText(err));
          } finally {
            setBusy("");
          }
        }}
      >
        <fieldset disabled={!!busy} className="grid cols-main-side" style={{ border: 0, padding: 0, margin: 0 }}>
        <Panel title="Budget & method">
          <div className="grid" style={{ gap: 14 }}>
            <label className="field">
              Budget to allocate (PKR)
              <input
                className="input"
                inputMode="decimal"
                placeholder="e.g. 1000000"
                value={budgetText}
                style={{ fontSize: 22, fontWeight: 800, minHeight: 52 }}
                aria-describedby="budget-hint"
                onChange={(e) => {
                  const text = e.target.value.replace(/[,\s]/g, "");
                  setBudgetText(text);
                  update({ budget: text === "" ? 0 : Number(text) });
                }}
              />
              <span className="hint" id="budget-hint">
                No default amount. PKR 0.01 – 100,000,000, up to two decimals.{" "}
                <button
                  type="button"
                  className="btn sm ghost"
                  onClick={() => {
                    setBudgetText("1000000");
                    update({ budget: 1_000_000 });
                  }}
                >
                  Fill the assignment example: Rs 1,000,000
                </button>
              </span>
            </label>
            <label className="field">
              Method
              <select
                className="select"
                value={config.method}
                onChange={(e) => {
                  const method = e.target.value as PlanMethod;
                  update({ method, model_id: method === "model" ? accepted[0]?.id ?? null : null });
                }}
              >
                {METHODS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              <span className="hint">{METHODS.find((m) => m.value === config.method)?.help}</span>
            </label>
            {config.method === "model" && (
              <label className="field">
                Accepted model
                <select className="select" value={config.model_id || ""} onChange={(e) => update({ model_id: e.target.value || null })}>
                  <option value="">Choose…</option>
                  {state.models.map((m) => (
                    <option key={m.id} value={m.id} disabled={!m.eligible}>
                      {m.algorithm} · {shortId(m.id)} · as-of {m.as_of_date} {m.eligible ? "" : "(rejected)"}
                    </option>
                  ))}
                </select>
                {!accepted.length && (
                  <span className="hint">
                    No accepted model yet. <Link href="/models">Train one</Link> or use another method.
                  </span>
                )}
              </label>
            )}
            <div className="form-grid">
              <label className="field">
                Plan start
                <input className="input" type="date" value={config.start_date} onChange={(e) => update({ start_date: e.target.value })} />
              </label>
              <label className="field">
                Horizon (days)
                <input className="input" type="number" min={1} max={30} value={config.horizon_days} onChange={(e) => update({ horizon_days: Number(e.target.value) })} />
              </label>
              {config.method !== "model" && (
                <>
                  <label className="field">
                    Label as-of date
                    <input className="input" type="date" value={config.as_of_date} onChange={(e) => update({ as_of_date: e.target.value })} />
                  </label>
                  <label className="field">
                    Label maturity lag (days)
                    <input className="input" type="number" min={0} max={90} value={config.label_lag_days} onChange={(e) => update({ label_lag_days: Number(e.target.value) })} />
                    <span className="hint">{dataset.is_synthetic ? "Synthetic data uses an effective lag of 0." : "Match your attribution window."}</span>
                  </label>
                </>
              )}
            </div>
          </div>
        </Panel>
        <Panel title="Platform limits" description="Defaults are 0%–100%. Add real account minimums/maximums when you know them.">
          <div className="grid" style={{ gap: 10 }}>
            {(dataset.options.platform || []).map((name) => {
              const limit = config.platforms.find((p) => p.platform === name);
              return (
                <fieldset key={name} className="panel flat" style={{ padding: 12, margin: 0 }}>
                  <legend className="sr-only">{name} limits</legend>
                  <label className="check" style={{ marginBottom: limit ? 8 : 0 }}>
                    <input
                      type="checkbox"
                      checked={!!limit}
                      onChange={(e) =>
                        update({
                          platforms: e.target.checked
                            ? [...config.platforms, { platform: name as PlatformLimit["platform"], min_percent: 0, max_percent: 100 }]
                            : config.platforms.filter((p) => p.platform !== name),
                        })
                      }
                    />
                    <PlatformLabel name={name} />
                  </label>
                  {limit && (
                    <div className="form-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))", gap: 8 }}>
                      <label className="field">
                        Min %
                        <input className="input" type="number" min={0} max={100} value={limit.min_percent} onChange={(e) => setLimit(name, { min_percent: Number(e.target.value) })} />
                      </label>
                      <label className="field">
                        Max %
                        <input className="input" type="number" min={0} max={100} value={limit.max_percent} onChange={(e) => setLimit(name, { max_percent: Number(e.target.value) })} />
                      </label>
                      <label className="field">
                        Min PKR
                        <input
                          className="input"
                          type="number"
                          min={0}
                          step="0.01"
                          value={limit.min_amount || ""}
                          onChange={(e) => setLimit(name, { min_amount: e.target.value ? Number(e.target.value) : 0 })}
                        />
                      </label>
                      <label className="field">
                        Max PKR
                        <input
                          className="input"
                          type="number"
                          min={0}
                          step="0.01"
                          value={limit.max_amount ?? ""}
                          onChange={(e) => setLimit(name, { max_amount: e.target.value ? Number(e.target.value) : null })}
                        />
                      </label>
                    </div>
                  )}
                </fieldset>
              );
            })}
          </div>
        </Panel>
        </fieldset>
        <div className="grid" style={{ marginTop: 18 }}>
          {issues.length > 0 && config.budget > 0 && (
            <Notice tone="warn" title="Fix before generating">
              <ul>
                {issues.map((i) => (
                  <li key={i}>{i}</li>
                ))}
              </ul>
            </Notice>
          )}
          <div className="btn-row">
            <button className="btn amber" type="submit" disabled={!!busy || issues.length > 0}>
              Generate recommendation
            </button>
            {state.plans.length > 0 && (
              <label className="field" style={{ gridAutoFlow: "column", alignItems: "center", gap: 8 }}>
                <History size={15} aria-hidden="true" />
                <span className="sr-only">Open a saved plan</span>
                <select
                  className="select"
                  style={{ minHeight: 40, maxWidth: 380 }}
                  value=""
                  onChange={async (e) => {
                    if (!e.target.value) return;
                    setBusy("Loading saved plan…");
                    try {
                      const p = await api<Plan>(`/optimizer/plans/${e.target.value}`);
                      setPlan(p);
                      setConfig(p.config);
                      setBudgetText(String(p.config.budget));
                    } catch (err) {
                      setError(errorText(err));
                    } finally {
                      setBusy("");
                    }
                  }}
                >
                  <option value="">Restore a saved plan ({state.plans.length})…</option>
                  {state.plans.map((p) => (
                    <option key={p.id} value={p.id}>
                      {pkr(p.totals.budget, 0)} · {p.method_label} · {dateTime(p.created_at)}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {busy && <Busy text={busy} />}
          {error && <Notice tone="error">{error}</Notice>}
        </div>
      </form>
      {plan ? <PlanView plan={plan} stale={stale} /> : <Notice>No plan yet for this source. Enter a budget and generate one.</Notice>}
      <ScenarioReview state={state} />
    </>
  );
}
