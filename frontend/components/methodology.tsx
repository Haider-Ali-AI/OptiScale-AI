"use client";

import { useState } from "react";
import { num, pct, pkr, ratio } from "@/lib/format";
import { useAnalytics } from "./overview";
import { PageHead, Panel, Segmented, SourceBadge } from "./ui";
import { useWorkspace } from "./workspace";

const KPIS = [
  { id: "ctr", name: "CTR (click-through rate)", formula: "CTR % = 100 × Σ clicks ÷ Σ impressions", meaning: "How often an ad shown was clicked.", num: "clicks", den: "impressions", scale: 100, fmt: pct },
  { id: "cpc", name: "CPC (cost per click)", formula: "CPC = Σ spend ÷ Σ clicks", meaning: "Average PKR paid for one click.", num: "spend", den: "clicks", scale: 1, fmt: pkr },
  { id: "cpa", name: "CPA (cost per acquisition)", formula: "CPA = Σ spend ÷ Σ conversions", meaning: "Average PKR paid per conversion as defined by the source.", num: "spend", den: "conversions", scale: 1, fmt: pkr },
  { id: "cvr", name: "Conversion rate", formula: "CVR % = 100 × Σ conversions ÷ Σ clicks", meaning: "Share of clicks that became conversions.", num: "conversions", den: "clicks", scale: 100, fmt: pct },
  { id: "roas", name: "ROAS (return on ad spend)", formula: "ROAS = Σ attributed revenue ÷ Σ spend", meaning: "Reported attributed revenue per rupee spent. It is not profit.", num: "revenue", den: "spend", scale: 1, fmt: ratio },
] as const;

function ExplainKpi() {
  const { dataset } = useWorkspace();
  const [id, setId] = useState<(typeof KPIS)[number]["id"]>("roas");
  const { data } = useAnalytics(dataset, {}, { group_by: "platform", page_size: "5" });
  const k = KPIS.find((x) => x.id === id)!;
  const t = data?.totals;
  return (
    <Panel title="Explain my KPI" description="Definition, formula and a worked example from the selected source's backend totals.">
      <Segmented label="KPI" value={id} onChange={setId} options={KPIS.map((x) => ({ value: x.id, label: x.id.toUpperCase() }))} />
      <div className="grid" style={{ gap: 10, marginTop: 14 }}>
        <strong>{k.name}</strong>
        <div className="formula">{k.formula}</div>
        <p className="muted" style={{ margin: 0 }}>
          {k.meaning} Aggregates always divide summed base values; per-row rates are never averaged. A missing value or a zero
          denominator gives “Not available”, never 0.
        </p>
        {dataset && t && (
          <div className="panel flat" style={{ padding: 14 }}>
            <div className="btn-row" style={{ marginBottom: 6 }}>
              <span className="faint">Worked example · {dataset.name}</span>
              <SourceBadge dataset={dataset} />
            </div>
            <div className="formula">
              {k.scale === 100 ? "100 × " : ""}
              {num(t[k.num], 2)} ÷ {num(t[k.den], 2)} = {k.fmt(t[k.id])}
            </div>
            <p className="faint" style={{ margin: "6px 0 0" }}>
              The result shown is the backend value for all rows of this source{dataset.is_synthetic ? "; it is simulated, not real performance" : ""}.
            </p>
          </div>
        )}
      </div>
    </Panel>
  );
}

export function Methodology() {
  return (
    <>
      <PageHead eyebrow="Methodology & help" title="How OptiScale AI calculates and decides">
        Definitions, data rules, model and causal limits, the Big Data comparison method and where every number comes from.
      </PageHead>
      <ExplainKpi />
      <div className="grid cols-2">
        <Panel title="Data rules">
          <ul className="muted" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6, fontSize: 14 }}>
            <li>All money is PKR. Non-PKR imports need a verified exchange rate; none is assumed.</li>
            <li>Revenue means reported attributed revenue. Profit is a different quantity and appears only in the commerce pilot when costs are recorded.</li>
            <li>Synthetic and real sources are stored separately and never mixed; synthetic stays labelled everywhere.</li>
            <li>Daily or weekly observations; weekly data keeps whole weeks. Monthly or mixed periods are blocked.</li>
            <li>Exact duplicates are removed only by your choice; conflicting duplicate keys block import.</li>
            <li>Exports neutralise spreadsheet formula injection (cells starting with = + − @).</li>
          </ul>
        </Panel>
        <Panel title="Machine learning">
          <ul className="muted" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6, fontSize: 14 }}>
            <li>XGBoost regressor of attributed revenue from spend, platform, date context and audience; outcomes and simulator ground truth are not features.</li>
            <li>Chronological split: train → validation (settings) → sealed holdout. Labels must be mature at the as-of date.</li>
            <li>Acceptance gate: ≥5% RMSE improvement over a train-only baseline on validation and holdout, WAPE ≤100%, minimum platform support, no platform much worse than baseline.</li>
            <li>A rejected model is shown with reasons and is never used for budget planning.</li>
          </ul>
        </Panel>
        <Panel title="Budget recommendation engine">
          <ul className="muted" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6, fontSize: 14 }}>
            <li>You enter the budget; there is no default amount.</li>
            <li>Predictions are turned into monotone concave response curves (diminishing returns), then a greedy exact-paisa allocator spends each increment where the marginal estimate is highest.</li>
            <li>Allocations always total the budget to the last paisa and obey every min/max share and PKR limit.</li>
            <li>Without an accepted model or a passing baseline screen, the engine still allocates within limits but withholds revenue/ROAS estimates.</li>
            <li>Results are advisory and observational. They are not causal uplift estimates and change no live spending.</li>
          </ul>
        </Panel>
        <Panel title="Big Data comparison">
          <ul className="muted" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 6, fontSize: 14 }}>
            <li>Inputs: seeded synthetic campaign rows at 10K, 100K, 1M and 10M, written as chunked Snappy Parquet.</li>
            <li>Workload: identical per-platform sums of impressions, clicks, spend, conversions and revenue, then weighted ratios.</li>
            <li>Engines: Pandas (in-memory or chunked), local MapReduce (process mappers + shuffle + reducer), local PySpark DataFrame.</li>
            <li>At least three measured repeats per engine; every repeat must match the reference answer exactly (scaled integer comparison).</li>
            <li>Single-machine measurements; Spark&apos;s distributed advantages do not appear on one laptop and are not claimed.</li>
          </ul>
        </Panel>
      </div>
      <Panel flat title="Not in scope (stated honestly)">
        <p className="muted" style={{ margin: 0 }}>
          No live connections to Facebook, Instagram, Google, TikTok, YouTube or Shopify accounts. No automatic campaign changes or
          real spending. No multi-user accounts: hosted mode is a single-owner workspace behind Basic authentication. Real merchant
          validation of the commerce pilot is pending.
        </p>
      </Panel>
    </>
  );
}
