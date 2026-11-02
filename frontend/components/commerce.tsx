"use client";

import { Download, FlaskConical, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, errorText, isAbort, post, type CommerceMeta, type CommerceReport, type CommerceState, type ProfitPlan, type Row } from "@/lib/api";
import { coverage, dateTime, NA, pct, pkr, ratio, shortId } from "@/lib/format";
import { Busy, ConfirmDialog, Empty, Kpi, LoadingPage, Notice, PageHead, Panel, PlatformLabel, Segmented } from "./ui";

/** Commerce reports store money in integer paisa. */
const fromPaisa = (v: number | null | undefined) => (v == null ? null : v / 100);
const STATUSES = ["all", "matched", "unmatched", "ambiguous", "excluded"] as const;

function Links({ id }: { id: string }) {
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");
  const [data, setData] = useState<{ rows: Row[]; total: number } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    api<{ rows: Row[]; total: number }>(`/commerce/snapshots/${id}/rows?table=links&status=${status}&page_size=100`, { signal: c.signal })
      .then(setData)
      .catch((e) => !isAbort(e) && setError(errorText(e)));
    return () => c.abort();
  }, [id, status]);
  return (
    <Panel
      title="Order attribution outcomes"
      description="Each store order and the evidence for (or against) a campaign match."
      actions={<Segmented label="Outcome filter" value={status} onChange={setStatus} options={STATUSES.map((s) => ({ value: s, label: s }))} />}
    >
      {error && <Notice tone="error">{error}</Notice>}
      {data && (
        <div className="table-wrap" style={{ maxHeight: 380 }}>
          <table className="data">
            <thead>
              <tr>
                <th scope="col">Order date</th>
                <th scope="col">Outcome</th>
                <th scope="col">Platform / campaign</th>
                <th scope="col" className="r">
                  Net sales
                </th>
                <th scope="col">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={String(r.order_key)}>
                  <td>{String(r.date)}</td>
                  <td>
                    <span className={`badge ${r.status === "matched" ? "ok" : r.status === "ambiguous" ? "amber" : r.status === "excluded" ? "" : "critical"}`}>
                      {String(r.status)}
                    </span>
                  </td>
                  <td>{r.platform ? <PlatformLabel name={String(r.platform)} /> : "—"} {r.campaign_id ? <span className="faint mono">{String(r.campaign_id)}</span> : null}</td>
                  <td className="r">{pkr(fromPaisa(r.net_sales as number | null))}</td>
                  <td className="muted" style={{ whiteSpace: "normal", minWidth: 240 }}>
                    {String(r.evidence ?? "")}
                  </td>
                </tr>
              ))}
              {!data.rows.length && (
                <tr>
                  <td colSpan={5} className="faint">
                    No orders with this outcome.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function ProfitPlanner({ report }: { report: CommerceReport }) {
  const platforms = report.ad_source.options.platform || [];
  const [budget, setBudget] = useState("");
  const [start, setStart] = useState("2026-10-31");
  const [horizon, setHorizon] = useState(7);
  const [plan, setPlan] = useState<ProfitPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!report.assessment.eligible)
    return (
      <Notice tone="warn" title="Profit-aware planning is gated for this comparison">
        <ul>
          {report.assessment.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        Descriptive contribution above remains inspectable; no profit forecast is produced.
      </Notice>
    );
  return (
    <Panel title="Contribution-profit plan" description="Available because this comparison passed the strict evidence and evaluation gates.">
      <form
        className="grid"
        style={{ gap: 12 }}
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            setPlan(
              await api<ProfitPlan>(
                "/commerce/profit-plans",
                post({
                  reconciliation_id: report.manifest.id,
                  budget,
                  start_date: start,
                  horizon_days: horizon,
                  platforms: platforms.map((p) => ({ platform: p, min_percent: 0, max_percent: 100 })),
                }),
              ),
            );
          } catch (err) {
            setError(errorText(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="form-grid">
          <label className="field">
            Budget (PKR)
            <input className="input" inputMode="decimal" required value={budget} placeholder="e.g. 5000.37" onChange={(e) => setBudget(e.target.value.trim())} />
          </label>
          <label className="field">
            Start
            <input className="input" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="field">
            Horizon (days)
            <input className="input" type="number" min={1} max={30} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} />
          </label>
        </div>
        <div className="btn-row">
          <button className="btn amber" type="submit" disabled={busy || !budget}>
            Generate contribution plan
          </button>
        </div>
        {busy && <Busy text="Planning…" />}
        {error && <Notice tone="error">{error}</Notice>}
      </form>
      {plan && (
        <div className="grid" style={{ marginTop: 14 }}>
          <div className="kpis">
            <Kpi label="Budget" value={pkr(plan.result.budget)} />
            <Kpi label="Est. contribution before ads" value={pkr(plan.result.estimated_contribution_before_ads)} />
            <Kpi label="Est. contribution profit" value={pkr(plan.result.estimated_contribution_profit)} sub="after ad spend" />
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Platform</th>
                  <th scope="col" className="r">
                    Amount
                  </th>
                  <th scope="col" className="r">
                    Supported range
                  </th>
                </tr>
              </thead>
              <tbody>
                {plan.result.allocations.map((a) => (
                  <tr key={a.platform}>
                    <th scope="row">
                      <PlatformLabel name={a.platform} />
                    </th>
                    <td className="r">{pkr(a.budget)}</td>
                    <td className="r faint">
                      {pkr(a.minimum)} – {pkr(a.maximum)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="faint">{plan.notice}</p>
          <div className="btn-row">
            <a className="btn sm" href={`/api/v1/commerce/snapshots/${plan.manifest.id}/export?format=csv`} download>
              <Download size={14} /> CSV
            </a>
            <a className="btn sm" href={`/api/v1/commerce/snapshots/${plan.manifest.id}/export`} download>
              <Download size={14} /> JSON
            </a>
          </div>
        </div>
      )}
    </Panel>
  );
}

function ReportView({ id }: { id: string }) {
  const [report, setReport] = useState<CommerceReport | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    api<CommerceReport>(`/commerce/snapshots/${id}`, { signal: c.signal })
      .then(setReport)
      .catch((e) => !isAbort(e) && setError(errorText(e)));
    return () => c.abort();
  }, [id]);
  if (error) return <Notice tone="error">{error}</Notice>;
  if (!report) return <LoadingPage label="Loading comparison" />;
  const r = report;
  return (
    <div className="grid">
      {r.manifest.is_synthetic && <Notice tone="warn">Fictional fixture. These figures exercise the real reconciliation code but validate no merchant.</Notice>}
      <Panel title="Three revenue origins, never added together" description={r.notice}>
        <div className="kpis">
          <Kpi label="Store net sales (order cohort)" value={pkr(fromPaisa(r.store.net_sales))} na={r.store.net_sales == null} sub={`coverage ${coverage(r.store.net_sales_coverage)}`} />
          <Kpi label="Platform-reported revenue" value={pkr(fromPaisa(r.advertising.platform_reported_revenue))} na={r.advertising.platform_reported_revenue == null} sub={`reported ROAS ${ratio(r.advertising.reported_roas)}`} />
          <Kpi label="Matched store sales" value={pkr(fromPaisa(r.attribution.matched_net_sales))} na={r.attribution.matched_net_sales == null} sub={`order coverage ${coverage(r.attribution.order_coverage)}`} />
          <Kpi label="Ad spend" value={pkr(fromPaisa(r.advertising.spend))} na={r.advertising.spend == null} />
        </div>
      </Panel>
      <div className="grid cols-2">
        <Panel title="Matching outcomes">
          <div className="kpis">
            <Kpi label="Matched" value={String(r.attribution.matched)} />
            <Kpi label="Unmatched" value={String(r.attribution.unmatched)} />
            <Kpi label="Ambiguous" value={String(r.attribution.ambiguous)} />
            <Kpi label="Excluded" value={String(r.attribution.excluded)} />
          </div>
          <dl className="dl" style={{ marginTop: 12 }}>
            <dt>Orders</dt>
            <dd>
              {r.store.unique_orders} unique · {r.store.eligible_orders} eligible · {r.store.excluded_orders} excluded
            </dd>
            <dt>Gross / discounts / refunds</dt>
            <dd className="num">
              {pkr(fromPaisa(r.store.gross_sales))} / {pkr(fromPaisa(r.store.discounts))} / {pkr(fromPaisa(r.store.merchandise_refunds))}
            </dd>
            <dt>Reference check</dt>
            <dd>
              {r.reference.provided_net_sales != null
                ? `net sales difference ${pkr(fromPaisa(r.reference.net_sales_difference))}, order count difference ${r.reference.order_count_difference}`
                : "No reference supplied"}
              <span className="faint" style={{ display: "block" }}>
                {r.reference.origin}
              </span>
            </dd>
          </dl>
        </Panel>
        <Panel title="Costs & contribution" description="Revenue is not profit. Contribution needs every variable cost to be recorded.">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Cost</th>
                  <th scope="col" className="r">
                    Total
                  </th>
                  <th scope="col" className="r">
                    Coverage
                  </th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(r.costs.totals).map((k) => (
                  <tr key={k}>
                    <th scope="row">{k.replaceAll("_", " ")}</th>
                    <td className="r">{pkr(fromPaisa(r.costs.totals[k]))}</td>
                    <td className="r">{coverage(r.costs.coverage[k])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <dl className="dl" style={{ marginTop: 12 }}>
            <dt>Contribution after ads</dt>
            <dd className="num" style={{ fontWeight: 800 }}>
              {pkr(fromPaisa(r.profit.contribution_after_ads))}
            </dd>
            <dt>Margin</dt>
            <dd className="num">{r.profit.margin == null ? NA : pct(r.profit.margin * 100, 1)}</dd>
            <dt>Merchandise MER</dt>
            <dd className="num">{ratio(r.profit.merchandise_mer)}</dd>
          </dl>
        </Panel>
      </div>
      <Links id={r.manifest.id} />
      <ProfitPlanner report={r} />
      <div className="btn-row">
        <a className="btn sm" href={`/api/v1/commerce/snapshots/${r.manifest.id}/export`} download>
          <Download size={14} /> Export comparison JSON
        </a>
        <a className="btn sm" href={`/api/v1/commerce/snapshots/${r.manifest.id}/export?format=csv&table=links`} download>
          <Download size={14} /> Export order links CSV
        </a>
      </div>
    </div>
  );
}

export function Commerce() {
  const [state, setState] = useState<CommerceState | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<CommerceMeta | null>(null);
  const load = useCallback(async () => {
    const s = await api<CommerceState>("/commerce");
    setState(s);
    return s;
  }, []);
  useEffect(() => {
    api<CommerceState>("/commerce")
      .then((s) => {
        setState(s);
        setSelected((cur) => cur || s.reconciliation[0]?.id || null);
      })
      .catch((e) => setError(errorText(e)));
  }, []);
  const demo = async (variant: "pilot" | "history") => {
    setBusy(variant === "pilot" ? "Importing the small fictional pilot through the real importer…" : "Importing 450 fictional historical orders…");
    setError("");
    try {
      const r = await api<{ reconciliation_id: string }>(`/commerce/demo?variant=${variant}`, post({}));
      await load();
      setSelected(r.reconciliation_id);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  };
  if (!state && !error) return <LoadingPage label="Loading commerce pilot" />;
  return (
    <>
      <PageHead eyebrow="Commerce & attribution" title="Store sales vs ad-reported revenue">
        A CSV-based pilot that compares store orders with a separately chosen ad export: evidenced matches, unmatched and
        ambiguous orders, cost coverage and gated contribution profit. No Shopify or ad account is connected.
      </PageHead>
      <Notice tone="info" title="What this release supports">
        Fictional pilot and history datasets below run the real importer, reconciler and profit gates. Importing your own
        order/cost CSVs and building custom UTM mappings is supported by the backend API (<code>/api/v1/commerce/imports/*</code>,{" "}
        <code>/reconciliations</code>) but does not have a screen in this SignalSpend release yet.
      </Notice>
      <Panel title="Try the verified pilot flows">
        <div className="btn-row">
          <button className="btn" type="button" disabled={!!busy} onClick={() => void demo("pilot")}>
            <FlaskConical size={15} /> Load fictional pilot (8 orders)
          </button>
          <button className="btn" type="button" disabled={!!busy} onClick={() => void demo("history")}>
            <FlaskConical size={15} /> Load complete fictional history (450 orders)
          </button>
        </div>
        <p className="faint">The pilot is deliberately gated (no profit forecast). The history fixture can pass the gates. Try PKR 5,000.37, start 2026-10-31, 7 days.</p>
        {busy && <Busy text={busy} />}
        {error && <Notice tone="error">{error}</Notice>}
      </Panel>
      {state && state.reconciliation.length > 0 ? (
        <Panel title="Saved comparisons">
          <div className="grid" style={{ gap: 8 }}>
            {state.reconciliation.map((m) => (
              <div key={m.id} className="btn-row" style={{ justifyContent: "space-between", borderBottom: "1px solid var(--line)", paddingBottom: 8 }}>
                <button className="btn sm" type="button" aria-pressed={selected === m.id} style={{ borderColor: selected === m.id ? "var(--teal)" : undefined }} onClick={() => setSelected(m.id)}>
                  {m.name || `Comparison ${shortId(m.id)}`}
                </button>
                <span className="faint">
                  {m.start_date} → {m.end_date} · {dateTime(m.created_at)} {m.is_synthetic && <span className="badge amber">fictional</span>}
                </span>
                <button className="btn sm danger" type="button" aria-label={`Delete comparison ${shortId(m.id)}`} onClick={() => setDeleting(m)}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </Panel>
      ) : (
        <Empty title="No commerce comparisons yet">Load one of the fictional pilot flows above.</Empty>
      )}
      {selected && <ReportView key={selected} id={selected} />}
      <ConfirmDialog
        open={!!deleting}
        title="Delete this comparison?"
        confirmLabel="Delete"
        onClose={() => setDeleting(null)}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await api(`/commerce/snapshots/${deleting.id}`, { method: "DELETE" });
            if (selected === deleting.id) setSelected(null);
            setDeleting(null);
            await load();
          } catch (e) {
            setError(errorText(e));
            setDeleting(null);
          }
        }}
      >
        The saved comparison and any profit plans derived from it are removed. Imported order snapshots stay until deleted separately.
      </ConfirmDialog>
    </>
  );
}
