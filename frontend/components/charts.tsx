"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,

  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { Aggregate } from "@/lib/api";
import { compact, num, pct, pkr, pkrShort, ratio } from "@/lib/format";
import { Marker, PLATFORM_COLOR, PLATFORM_SHAPE, PlatformLabel } from "./ui";

const axis = { stroke: "var(--text-3)", fontSize: 12 };
const grid = <CartesianGrid stroke="var(--line)" strokeDasharray="3 4" vertical={false} />;

function Tip({ active, payload, label, fmt }: { active?: boolean; payload?: { name: string; value: number; color?: string }[]; label?: string; fmt?: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tt">
      {label && <div style={{ fontWeight: 700, marginBottom: 4 }}>{label}</div>}
      {payload.map((p) => (
        <div key={p.name} className="num">
          {p.name}: {fmt ? fmt(p.value) : num(p.value, 2)}
        </div>
      ))}
    </div>
  );
}

/** Accessible alternative: every chart is paired with a table toggle. */
export function ChartTable({ rows, columns }: { rows: (string | number)[][]; columns: string[] }) {
  return (
    <details className="disclose" style={{ marginTop: 10 }}>
      <summary className="faint">Show chart data as a table</summary>
      <div className="table-wrap" style={{ marginTop: 8 }}>
        <table className="data">
          <thead>
            <tr>
              {columns.map((c, i) => (
                <th key={c} className={i ? "r" : ""} scope="col">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {r.map((v, j) => (
                  <td key={j} className={j ? "r" : ""}>
                    {v}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export type PlatformMetric = "spend" | "revenue" | "roas" | "ctr" | "cpc" | "cpa" | "cvr";
export const METRIC_LABEL: Record<PlatformMetric, string> = {
  spend: "Spend (PKR)",
  revenue: "Attributed revenue (PKR)",
  roas: "ROAS",
  ctr: "CTR %",
  cpc: "CPC (PKR)",
  cpa: "CPA (PKR)",
  cvr: "Conversion rate %",
};
export const fmtMetric = (m: PlatformMetric, v: number | null) =>
  m === "spend" || m === "revenue" ? pkrShort(v) : m === "roas" ? ratio(v) : m === "ctr" || m === "cvr" ? pct(v) : pkr(v);

export function PlatformBars({ data, metric }: { data: Aggregate[]; metric: PlatformMetric }) {
  const rows = data.map((d) => ({ name: d.name, value: d[metric] }));
  const missing = rows.filter((r) => r.value == null).map((r) => r.name);
  return (
    <div>
      <div className="chart-box" role="img" aria-label={`${METRIC_LABEL[metric]} by platform bar chart`}>
        <ResponsiveContainer>
          <BarChart data={rows.filter((r) => r.value != null)} layout="vertical" margin={{ left: 8, right: 24 }}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="3 4" horizontal={false} />
            <XAxis type="number" {...axis} tickFormatter={(v) => compact(v)} />
            <YAxis type="category" dataKey="name" {...axis} width={84} />
            <Tooltip cursor={{ fill: "var(--card-2)" }} content={<Tip fmt={(v) => fmtMetric(metric, v)} />} />
            <Bar dataKey="value" name={METRIC_LABEL[metric]} radius={[0, 6, 6, 0]} barSize={22}>
              {rows
                .filter((r) => r.value != null)
                .map((r) => (
                  <Cell key={r.name} fill={PLATFORM_COLOR[r.name] || "var(--teal)"} />
                ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {missing.length > 0 && <p className="faint">Not available (incomplete inputs): {missing.join(", ")}</p>}
      <ChartTable columns={["Platform", METRIC_LABEL[metric]]} rows={rows.map((r) => [r.name, fmtMetric(metric, r.value)])} />
    </div>
  );
}

export function TrendChart({ data, grain }: { data: Aggregate[]; grain: string }) {
  const rows = data.map((d) => ({ name: d.name, Spend: d.spend, Revenue: d.revenue }));
  return (
    <div>
      <div className="chart-box" role="img" aria-label={`Spend and attributed revenue per ${grain} line chart`}>
        <ResponsiveContainer>
          <AreaChart data={rows} margin={{ left: 0, right: 12, top: 8 }}>
            <defs>
              <linearGradient id="gRev" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0" stopColor="var(--teal)" stopOpacity={0.35} />
                <stop offset="1" stopColor="var(--teal)" stopOpacity={0} />
              </linearGradient>
            </defs>
            {grid}
            <XAxis dataKey="name" {...axis} minTickGap={28} />
            <YAxis {...axis} tickFormatter={(v) => compact(v)} width={48} />
            <Tooltip content={<Tip fmt={(v) => pkr(v, 0)} />} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Area type="monotone" dataKey="Revenue" stroke="var(--teal)" fill="url(#gRev)" strokeWidth={2} connectNulls={false} />
            <Area type="monotone" dataKey="Spend" stroke="var(--amber)" fill="transparent" strokeWidth={2} strokeDasharray="5 4" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="faint">
        One point per {grain}. Revenue is reported attributed revenue, not profit. Gaps mean incomplete observations.
      </p>
      <ChartTable
        columns={["Period", "Spend", "Attributed revenue"]}
        rows={rows.map((r) => [r.name, pkr(r.Spend), pkr(r.Revenue)])}
      />
    </div>
  );
}

/** Bespoke funnel; only drawn when all three stage totals are complete. */
export function Funnel({ impressions, clicks, conversions }: { impressions: number | null; clicks: number | null; conversions: number | null }) {
  if (impressions == null || clicks == null || conversions == null || impressions <= 0)
    return (
      <p className="muted">
        The funnel needs complete impressions, clicks and conversions for the current selection. At least one stage is
        incomplete, so it is not drawn.
      </p>
    );
  const stages = [
    { label: "Impressions", value: impressions, color: "var(--peri)" },
    { label: "Clicks", value: clicks, color: "var(--teal)" },
    { label: "Conversions", value: conversions, color: "var(--amber)" },
  ];
  return (
    <div className="grid" style={{ gap: 12 }} role="list" aria-label="Campaign funnel">
      {stages.map((s, i) => {
        // Log scale keeps the conversion stage visible; true counts are always printed.
        const width = Math.max(6, (Math.log10(s.value + 1) / Math.log10(impressions + 1)) * 100);
        const step = i ? (s.value / stages[i - 1].value) * 100 : null;
        return (
          <div key={s.label} role="listitem">
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, gap: 8 }}>
              <strong>{s.label}</strong>
              <span className="num">
                {num(s.value)}
                {step != null && <span className="faint"> · {pct(step)} of previous</span>}
              </span>
            </div>
            <div className="bar-track" style={{ height: 16, marginTop: 5 }}>
              <div className="bar-fill" style={{ width: `${width}%`, background: s.color }} />
            </div>
          </div>
        );
      })}
      <p className="faint" style={{ margin: 0 }}>
        Bar length uses a log scale so small stages stay visible; labels show exact backend totals.
      </p>
    </div>
  );
}

/** Spend share (x) vs observed ROAS (y); bubble = attributed revenue. Descriptive, not causal. */
export function OpportunityMatrix({ data }: { data: Aggregate[] }) {
  const totalSpend = data.reduce((s, d) => s + (d.spend ?? 0), 0);
  const complete = data.every((d) => d.spend != null);
  const points = data
    .filter((d) => d.spend != null && d.roas != null && totalSpend > 0)
    .map((d) => ({ name: d.name, share: ((d.spend as number) / totalSpend) * 100, roas: d.roas as number, revenue: d.revenue ?? 0 }));
  if (!complete || !points.length)
    return <p className="muted">Spend or ROAS is incomplete for at least one platform, so shares cannot be compared truthfully.</p>;
  return (
    <div>
      <div className="chart-box" role="img" aria-label="Platform opportunity matrix scatter chart: spend share against observed ROAS">
        <ResponsiveContainer>
          <ScatterChart margin={{ left: 0, right: 16, top: 12, bottom: 8 }}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="3 4" />
            <XAxis type="number" dataKey="share" name="Spend share" unit="%" {...axis} domain={[0, "auto"]} />
            <YAxis type="number" dataKey="roas" name="ROAS" {...axis} width={44} tickFormatter={(v) => `${v}×`} />
            <ZAxis type="number" dataKey="revenue" range={[120, 900]} />
            <Tooltip
              content={({ active, payload }) =>
                active && payload?.length ? (
                  <div className="tt">
                    <strong>{payload[0].payload.name}</strong>
                    <div className="num">Spend share {pct(payload[0].payload.share, 1)}</div>
                    <div className="num">Observed ROAS {ratio(payload[0].payload.roas)}</div>
                    <div className="num">Revenue {pkrShort(payload[0].payload.revenue)}</div>
                  </div>
                ) : null
              }
            />
            {points.map((p) => (
              <Scatter key={p.name} name={p.name} data={[p]} fill={PLATFORM_COLOR[p.name]} fillOpacity={0.85} shape={PLATFORM_SHAPE[p.name] || "circle"} />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="btn-row" style={{ gap: 14, fontSize: 13 }}>
        {points.map((p) => (
          <PlatformLabel key={p.name} name={p.name} />
        ))}
      </div>
      <p className="faint">
        Upper-left = high observed ROAS on a small share of spend. This is an association in historical data, not proof that
        moving budget would raise revenue.
      </p>
      <ChartTable
        columns={["Platform", "Spend share", "Observed ROAS", "Attributed revenue"]}
        rows={points.map((p) => [p.name, pct(p.share, 1), ratio(p.roas), pkr(p.revenue)])}
      />
    </div>
  );
}

/** Horizontal stacked share bar + legend; amounts come straight from the plan. */
export function AllocationBar({ items }: { items: { platform: string; budget: number; share_percent: number }[] }) {
  return (
    <div>
      <div className="stack-bar" role="img" aria-label={`Allocation: ${items.map((i) => `${i.platform} ${i.share_percent.toFixed(2)}%`).join(", ")}`}>
        {items
          .filter((i) => i.budget > 0)
          .map((i) => (
            <span key={i.platform} style={{ width: `${i.share_percent}%`, background: PLATFORM_COLOR[i.platform] }} title={`${i.platform} ${i.share_percent.toFixed(2)}%`} />
          ))}
      </div>
      <div className="btn-row" style={{ gap: 16, marginTop: 10, fontSize: 13 }}>
        {items.map((i) => (
          <span key={i.platform} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <Marker platform={i.platform} />
            {i.platform} <strong className="num">{i.share_percent.toFixed(2)}%</strong>
          </span>
        ))}
      </div>
    </div>
  );
}

export function CurveChart({ curves }: { curves: { platform: string; points: { budget: number; adjusted_revenue: number }[] }[] }) {
  if (!curves.length) return null;
  return (
    <div className="chart-box" role="img" aria-label="Planning response curves: adjusted estimated revenue against platform budget">
      <ResponsiveContainer>
        <ScatterChart margin={{ left: 0, right: 12, top: 8 }}>
          {grid}
          <XAxis type="number" dataKey="budget" name="Budget" {...axis} tickFormatter={(v) => compact(v)} domain={["dataMin", "dataMax"]} />
          <YAxis type="number" dataKey="adjusted_revenue" name="Revenue" {...axis} tickFormatter={(v) => compact(v)} width={48} />
          <Tooltip
            content={({ active, payload }) =>
              active && payload?.length ? (
                <div className="tt num">
                  Budget {pkr(Number(payload[0].payload.budget), 0)}
                  <br />
                  Adjusted revenue {pkr(Number(payload[0].payload.adjusted_revenue), 0)}
                </div>
              ) : null
            }
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {curves.map((c) => (
            <Scatter key={c.platform} name={c.platform} data={c.points} fill={PLATFORM_COLOR[c.platform]} line={{ stroke: PLATFORM_COLOR[c.platform], strokeWidth: 2 }} lineType="joint" shape={() => <g />} legendType={PLATFORM_SHAPE[c.platform] || "circle"} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SimpleBars({ data, color = "var(--peri)", fmt, label }: { data: { name: string; value: number }[]; color?: string; fmt: (v: number) => string; label: string }) {
  return (
    <div className="chart-box" style={{ height: Math.max(160, data.length * 34 + 40) }} role="img" aria-label={label}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="3 4" horizontal={false} />
          <XAxis type="number" {...axis} tickFormatter={(v) => fmt(v)} />
          <YAxis type="category" dataKey="name" {...axis} width={120} />
          <Tooltip cursor={{ fill: "var(--card-2)" }} content={<Tip fmt={fmt} />} />
          <Bar dataKey="value" name={label} fill={color} radius={[0, 6, 6, 0]} barSize={18} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
