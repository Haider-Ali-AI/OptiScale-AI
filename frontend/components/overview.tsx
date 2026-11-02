"use client";

import { Download, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, errorText, isAbort, type Aggregate, type Analytics, type Manifest, type WorkspaceState } from "@/lib/api";
import { coverage, num, NA, pct, pkr, pkrShort, ratio } from "@/lib/format";
import { Funnel, METRIC_LABEL, OpportunityMatrix, PlatformBars, TrendChart, type PlatformMetric } from "./charts";
import { FilterBar } from "./filters";
import { Kpi, LoadingPage, NeedDataset, Notice, PageHead, Panel, PlatformLabel, SourceBadge } from "./ui";
import { useWorkspace, type Filters } from "./workspace";

export function useAnalytics(dataset: Manifest | null, filters: Filters, extra: Record<string, string>) {
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const key = JSON.stringify([dataset?.id, filters, extra]);
  useEffect(() => {
    if (!dataset) return;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    const q = new URLSearchParams({ ...(filters as Record<string, string>), ...extra });
    api<Analytics>(`/datasets/${dataset.id}/analytics?${q}`, { signal: controller.signal })
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e) => !isAbort(e) && setError(errorText(e)))
      .finally(() => !controller.signal.aborted && setLoading(false));
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { data, error, loading };
}

export const exportHref = (dataset: Manifest, filters: Filters) =>
  `/api/v1/datasets/${dataset.id}/export?${new URLSearchParams(filters as Record<string, string>)}`;

/** Ranks backend aggregates; the only client arithmetic is spend share = platform spend / summed spend. */
function Story({ platforms }: { platforms: Aggregate[] }) {
  const withRoas = platforms.filter((p) => p.roas != null);
  const withCpc = platforms.filter((p) => p.cpc != null);
  const spendKnown = platforms.every((p) => p.spend != null);
  const total = spendKnown ? platforms.reduce((s, p) => s + (p.spend as number), 0) : 0;
  const top = [...withRoas].sort((a, b) => (b.roas as number) - (a.roas as number))[0];
  const low = [...withRoas].sort((a, b) => (a.roas as number) - (b.roas as number))[0];
  const cpc = [...withCpc].sort((a, b) => (b.cpc as number) - (a.cpc as number))[0];
  const big = spendKnown && total > 0 ? [...platforms].sort((a, b) => (b.spend as number) - (a.spend as number))[0] : null;
  const lines: { label: string; text: React.ReactNode }[] = [];
  if (top)
    lines.push({
      label: "Highest observed ROAS",
      text: (
        <>
          <PlatformLabel name={top.name} /> returned <strong className="num">{ratio(top.roas)}</strong> attributed revenue per rupee
          {low && low.name !== top.name && (
            <>
              {" "}
              versus <strong className="num">{ratio(low.roas)}</strong> on {low.name}
            </>
          )}
          .
        </>
      ),
    });
  if (big)
    lines.push({
      label: "Largest spend share",
      text: (
        <>
          <PlatformLabel name={big.name} /> absorbed <strong className="num">{pct(((big.spend as number) / total) * 100, 1)}</strong> of spend (
          {pkrShort(big.spend)}).
        </>
      ),
    });
  if (cpc)
    lines.push({
      label: "Most expensive click",
      text: (
        <>
          <PlatformLabel name={cpc.name} /> has the highest CPC at <strong className="num">{pkr(cpc.cpc)}</strong>.
        </>
      ),
    });
  return (
    <Panel title="Marketing performance story" description="Plain-language ranking of the backend platform aggregates for the current filters.">
      {lines.length ? (
        <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 12 }}>
          {lines.map((l) => (
            <li key={l.label} style={{ borderLeft: "2px solid var(--amber)", paddingLeft: 12 }}>
              <div className="faint">{l.label}</div>
              <div>{l.text}</div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">Ratios are unavailable for this selection because required totals are incomplete.</p>
      )}
      <p className="faint" style={{ marginBottom: 0 }}>
        Rankings describe what happened in this window. They are not causal estimates of what extra spend would do.
      </p>
    </Panel>
  );
}

function TrustPanel({ dataset, state }: { dataset: Manifest; state: WorkspaceState }) {
  const fields = Object.entries(dataset.coverage);
  return (
    <Panel
      title={
        <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
          <ShieldCheck size={18} color="var(--teal)" aria-hidden="true" /> Data trust panel
        </span>
      }
      description="Where these numbers come from and what is missing."
    >
      <dl className="dl">
        <dt>Source</dt>
        <dd>
          <SourceBadge dataset={dataset} /> {dataset.original_filename || (dataset.seed != null ? `seed ${dataset.seed}` : "")}
        </dd>
        <dt>Observed period</dt>
        <dd className="num">
          {dataset.date_start} → {dataset.date_end} · {dataset.date_granularity}
        </dd>
        <dt>Rows</dt>
        <dd className="num">{num(dataset.rows)}</dd>
        <dt>Currency</dt>
        <dd>
          PKR{dataset.original_currency !== "PKR" ? ` (converted from ${dataset.original_currency} at ${dataset.exchange_rate})` : ""}
        </dd>
        <dt>Conversions</dt>
        <dd>{dataset.conversion_definition}</dd>
        <dt>Attribution</dt>
        <dd>{dataset.attribution_window}</dd>
        <dt>Revenue source</dt>
        <dd>{dataset.revenue_source === "synthetic" ? "Simulated" : "Ad-platform reported (attributed, not profit)"}</dd>
        <dt>Model readiness</dt>
        <dd>
          {state.model_status === "validated" ? (
            <span className="badge ok">Accepted model exists</span>
          ) : state.model_status === "trained" ? (
            <span className="badge amber">Trained · not accepted</span>
          ) : (
            <span className="badge">Not trained</span>
          )}
        </dd>
      </dl>
      <div style={{ marginTop: 14, display: "grid", gap: 8 }}>
        <div className="faint">Field coverage</div>
        {fields.map(([k, v]) => (
          <div key={k} style={{ display: "grid", gridTemplateColumns: "100px minmax(0,1fr) 56px", gap: 10, alignItems: "center", fontSize: 13 }}>
            <span>{k}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${v * 100}%`, background: v < 1 ? "var(--amber)" : "var(--teal)" }} />
            </div>
            <span className="num" style={{ textAlign: "right" }}>
              {coverage(v)}
            </span>
          </div>
        ))}
      </div>
      {dataset.warnings.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <Notice tone="warn">
            <ul style={{ margin: 0 }}>
              {dataset.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </Notice>
        </div>
      )}
    </Panel>
  );
}

export function KpiStrip({ totals }: { totals: Analytics["totals"] }) {
  const t = totals;
  return (
    <div className="kpis" aria-label="Key performance indicators">
      <Kpi label="Spend" value={pkrShort(t.spend)} na={t.spend == null} sub={t.spend != null ? pkr(t.spend) : "Incomplete spend"} />
      <Kpi label="Impressions" value={num(t.impressions)} na={t.impressions == null} />
      <Kpi label="Clicks" value={num(t.clicks)} na={t.clicks == null} />
      <Kpi label="Conversions" value={num(t.conversions, 2)} na={t.conversions == null} />
      <Kpi label="Attributed revenue" value={pkrShort(t.revenue)} na={t.revenue == null} sub="Reported, not profit" />
      <Kpi label="CTR" value={pct(t.ctr)} na={t.ctr == null} help="100 × Σclicks ÷ Σimpressions" />
      <Kpi label="CPC" value={pkr(t.cpc)} na={t.cpc == null} help="Σspend ÷ Σclicks" />
      <Kpi label="CPA" value={pkr(t.cpa)} na={t.cpa == null} help="Σspend ÷ Σconversions" />
      <Kpi label="Conversion rate" value={pct(t.cvr)} na={t.cvr == null} help="100 × Σconversions ÷ Σclicks" />
      <Kpi label="ROAS" value={ratio(t.roas)} na={t.roas == null} help="Σattributed revenue ÷ Σspend" />
    </div>
  );
}

export function Overview() {
  const { dataset, state, filters, loading: wsLoading } = useWorkspace();
  const [metric, setMetric] = useState<PlatformMetric>("roas");
  const { data, error, loading } = useAnalytics(dataset, filters, { group_by: "platform", page_size: "5" });
  if (wsLoading) return <LoadingPage label="Loading workspace" />;
  if (!dataset || !state)
    return (
      <>
        <PageHead eyebrow="Executive overview" title="Performance at a glance" />
        <NeedDataset />
      </>
    );
  return (
    <>
      <PageHead
        eyebrow="Executive overview"
        title={dataset.name}
        actions={
          <a className="btn sm" href={exportHref(dataset, filters)} download>
            <Download size={15} /> Export filtered CSV
          </a>
        }
      >
        Weighted totals computed by the backend from summed base values. Ratios with an incomplete or zero denominator show “{NA}”.
      </PageHead>
      {dataset.is_synthetic && (
        <Notice tone="warn" title="Synthetic demo data">
          Every number on this screen is simulated. It demonstrates the method, not real business performance.
        </Notice>
      )}
      <FilterBar dataset={dataset} />
      {error && <Notice tone="error">{error}</Notice>}
      {!data && loading && <LoadingPage label="Loading analytics" />}
      {data && (
        <div className="grid" style={{ opacity: loading ? 0.6 : 1, transition: "opacity 160ms" }} aria-busy={loading}>
          {data.totals.rows === 0 ? (
            <Notice tone="info" title="No rows match these filters">
              Reset or widen the filters to see results.
            </Notice>
          ) : (
            <>
              <KpiStrip totals={data.totals} />
              <div className="grid cols-main-side">
                <Panel
                  title="Platform comparison"
                  description="Same metric across all platforms in this selection."
                  actions={
                    <label className="field" style={{ minWidth: 180 }}>
                      <span className="sr-only">Metric</span>
                      <select className="select" value={metric} onChange={(e) => setMetric(e.target.value as PlatformMetric)}>
                        {(Object.keys(METRIC_LABEL) as PlatformMetric[]).map((m) => (
                          <option key={m} value={m}>
                            {METRIC_LABEL[m]}
                          </option>
                        ))}
                      </select>
                    </label>
                  }
                >
                  <PlatformBars data={data.platforms} metric={metric} />
                </Panel>
                <Story platforms={data.platforms} />
              </div>
              <Panel title="Performance timeline" description={`Spend and attributed revenue per ${data.trend_grain}.`}>
                <TrendChart data={data.trend} grain={data.trend_grain} />
              </Panel>
              <div className="grid cols-2">
                <Panel title="Campaign funnel" description="Impressions → clicks → conversions for the current filters.">
                  <Funnel impressions={data.totals.impressions} clicks={data.totals.clicks} conversions={data.totals.conversions} />
                </Panel>
                <Panel title="Platform opportunity matrix" description="Share of spend against observed ROAS.">
                  <OpportunityMatrix data={data.platforms} />
                </Panel>
              </div>
              <div className="grid cols-main-side">
                <TrustPanel dataset={dataset} state={state} />
                <Panel title="Next decision" description="Turn this evidence into an allocation.">
                  <p className="muted" style={{ marginTop: 0 }}>
                    Enter your own PKR budget and platform limits. The planner uses an accepted model, a screened historical
                    rule or allocation only, and tells you which one it used.
                  </p>
                  <div className="btn-row">
                    <Link className="btn amber" href="/budget">
                      Plan a budget
                    </Link>
                    <Link className="btn" href="/campaigns">
                      Drill into campaigns
                    </Link>
                  </div>
                </Panel>
              </div>
            </>
          )}
        </div>
      )}
    </>
  );
}
