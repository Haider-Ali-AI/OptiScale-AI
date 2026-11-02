"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, PLATFORMS, type LabState, type OptimizerState } from "@/lib/api";
import { compact, engineName, pkr } from "@/lib/format";
import { LoadingPage, PageHead, Panel } from "./ui";
import { useWorkspace } from "./workspace";

type Check = "done" | "partial" | "todo";
const Badge = ({ s }: { s: Check }) => (
  <span className={`badge ${s === "done" ? "ok" : s === "partial" ? "amber" : ""}`}>{s === "done" ? "evidence present" : s === "partial" ? "partial" : "not yet"}</span>
);

const FIELDS = ["date", "campaign", "platform", "impressions", "clicks", "spend", "conversions", "revenue", "age", "gender", "city", "device"];

/** University Story Mode: every status below is read live from the API, never hard-coded. */
export function Story() {
  const { dataset, state, loading } = useWorkspace();
  const [lab, setLab] = useState<LabState | null>(null);
  const [opt, setOpt] = useState<OptimizerState | null>(null);
  useEffect(() => {
    api<LabState>("/lab").then(setLab).catch(() => setLab(null));
  }, []);
  useEffect(() => {
    if (!dataset) return;
    api<OptimizerState>("/optimizer").then(setOpt).catch(() => setOpt(null));
  }, [dataset]);
  if (loading) return <LoadingPage label="Loading evidence" />;

  const platformsPresent = dataset ? PLATFORMS.filter((p) => dataset.options.platform?.includes(p)) : [];
  const fieldsPresent = dataset ? FIELDS.filter((f) => ["date", "campaign", "platform"].includes(f) || (dataset.coverage[f] ?? 0) > 0) : [];
  const completed = (lab?.jobs || []).filter((j) => j.status === "completed" && j.config.kind === "benchmark");
  const scalesDone = [10_000, 100_000, 1_000_000, 10_000_000].filter((s) => completed.some((j) => j.config.rows === s));
  const enginesDone = ["pandas", "mapreduce", "spark"].filter((e) => completed.some((j) => j.results.some((r) => r.engine === e && r.status === "completed")));
  const millionPlan = opt?.plans.find((p) => p.totals.budget === 1_000_000);

  const steps: { title: string; req: string; status: Check; evidence: string; href: string; cta: string }[] = [
    {
      title: "Five advertising platforms",
      req: "Facebook, Instagram, Google, TikTok, YouTube",
      status: platformsPresent.length === 5 ? "done" : platformsPresent.length ? "partial" : "todo",
      evidence: dataset ? `Selected source contains: ${platformsPresent.join(", ") || "none"}` : "No source selected",
      href: "/data",
      cta: "Data studio",
    },
    {
      title: "Required data fields",
      req: FIELDS.join(", "),
      status: fieldsPresent.length === FIELDS.length ? "done" : fieldsPresent.length ? "partial" : "todo",
      evidence: dataset ? `${fieldsPresent.length}/${FIELDS.length} fields populated in ${dataset.name}` : "No source selected",
      href: "/data",
      cta: "Inspect provenance",
    },
    {
      title: "KPIs: CTR, CPC, CPA, conversion rate, ROAS, revenue, campaign performance",
      req: "Weighted from summed base values",
      status: dataset ? "done" : "todo",
      evidence: dataset ? "Computed by the backend for the selected source; see overview and campaign explorer" : "Needs a source",
      href: "/overview",
      cta: "Executive overview",
    },
    {
      title: "Big Data simulation: 10K → 100K → 1M → 10M",
      req: "Generate each scale",
      status: scalesDone.length === 4 ? "done" : scalesDone.length ? "partial" : "todo",
      evidence: lab ? `Completed benchmark scales: ${scalesDone.map(compact).join(", ") || "none"}` : "Lab state unavailable",
      href: "/lab",
      cta: "Big Data lab",
    },
    {
      title: "Compare Pandas vs MapReduce vs Spark",
      req: "Same workload, measured repeats, correctness",
      status: enginesDone.length === 3 ? "done" : enginesDone.length ? "partial" : "todo",
      evidence: lab
        ? `Engines with completed runs: ${enginesDone.map(engineName).join(", ") || "none"}${lab.environment.engines.find((e) => e.id === "spark")?.available ? "" : " · Spark runtime not available here"}`
        : "Lab state unavailable",
      href: "/lab",
      cta: "Run or inspect",
    },
    {
      title: "Validated revenue model",
      req: "Chronological evaluation vs baseline",
      status: state?.model_status === "validated" ? "done" : state?.model_status === "trained" ? "partial" : "todo",
      evidence: state ? `Model status for the selected source: ${state.model_status.replace("_", " ")}` : "—",
      href: "/models",
      cta: "ML validation studio",
    },
    {
      title: "Marketing Budget Recommendation Engine: where should Rs 1 million go?",
      req: "User-entered PKR 1,000,000, exact allocation with reasons",
      status: millionPlan ? "done" : opt?.plans.length ? "partial" : "todo",
      evidence: millionPlan
        ? `Saved plan ${pkr(millionPlan.totals.budget, 0)} · ${millionPlan.method_label}`
        : opt?.plans.length
          ? `${opt.plans.length} plan(s) saved, none for exactly PKR 1,000,000`
          : "No saved plan yet. Enter 1000000 in the budget studio",
      href: "/budget",
      cta: "Budget decision studio",
    },
  ];
  return (
    <>
      <PageHead eyebrow="University story mode" title="Project 2 walkthrough: requirement → screen → evidence">
        Follow the steps in order for a live demonstration. Every status is read from the running backend now, so it reflects what
        has actually been generated, measured, trained and saved.
      </PageHead>
      <Panel title="Assignment checklist">
        {steps.map((s, i) => (
          <div className="story-step" key={s.title}>
            <span className="step-dot">{i + 1}</span>
            <div style={{ display: "grid", gap: 6 }}>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <strong>{s.title}</strong>
                <Badge s={s.status} />
              </div>
              <span className="faint">{s.req}</span>
              <span className="muted" style={{ fontSize: 14 }}>
                {s.evidence}
              </span>
              <div>
                <Link className="btn sm" href={s.href}>
                  {s.cta} →
                </Link>
              </div>
            </div>
          </div>
        ))}
      </Panel>
      <Panel flat title="Suggested 10-minute demo script">
        <ol className="muted" style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 6, fontSize: 14 }}>
          <li>Welcome → generate the seed-42 synthetic demo (10,000 rows, all five platforms).</li>
          <li>Executive overview → read the KPI strip, platform comparison, funnel and opportunity matrix; filter to one platform.</li>
          <li>Campaign explorer → group by campaign, sort by ROAS, export the selection.</li>
          <li>Big Data lab → show the saved 10K/100K/1M/10M matrix and correctness checks; run a fresh 10K live.</li>
          <li>ML validation studio → train with as-of 2026-10-29; explain the holdout vs baseline and the acceptance gate.</li>
          <li>Budget decision studio → enter 1000000, start 2026-10-30, Automatic, 0–100% limits; show the exact-total check and reasons. Then cap Google at 20% and regenerate.</li>
          <li>Methodology → formulas and limitations; state clearly that results are simulated and advisory.</li>
        </ol>
      </Panel>
    </>
  );
}
