"use client";

import { ArrowRight, BookOpen, Database, Sparkles, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api, errorText, post, type Manifest } from "@/lib/api";
import { Busy, Notice, Panel } from "./ui";
import { useWorkspace } from "./workspace";

export function Welcome() {
  const { state, refresh } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<Manifest | null>(null);
  const existingDemo = state?.datasets.find((d) => d.source === "synthetic_generator" && d.seed === 42 && d.rows === 10000);
  return (
    <>
      <section className="hero">
        <div className="eyebrow">Enterprise Marketing Intelligence & Optimization Engine</div>
        <h1>Where should the next rupee of ad spend go?</h1>
        <p>
          OptiScale AI turns campaign history from Facebook, Instagram, Google, TikTok and YouTube into weighted KPIs, a
          measured Pandas vs MapReduce vs Spark comparison, a validated revenue model and an exact PKR budget recommendation,
          with every assumption labelled.
        </p>
        <div className="btn-row" style={{ marginTop: 22 }}>
          <span className="badge">{state?.hosting_notice ? "Hosted single-owner workspace" : "Local single-user workspace"}</span>
          <span className="badge">No ad or Shopify accounts connected</span>
          <span className="badge">No live spending changes</span>
          {state && <span className="badge teal">{state.dataset_count} saved dataset{state.dataset_count === 1 ? "" : "s"}</span>}
        </div>
      </section>

      <div className="grid cols-3">
        <div className="panel path-card">
          <Sparkles size={22} color="var(--amber)" aria-hidden="true" />
          <h3>Explore synthetic demo</h3>
          <p>
            Generate the reproducible 10,000-row seed-42 demo (Jan–Mar 2026, all five platforms). Every result stays labelled
            synthetic.
          </p>
          {existingDemo ? (
            <Link className="btn primary" href="/overview">
              Open the saved demo <ArrowRight size={16} />
            </Link>
          ) : (
            <button
              className="btn primary"
              type="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  const m = await api<Manifest>(
                    "/datasets/generate",
                    post({ name: "Pakistan campaign demo", rows: 10000, seed: 42, start_date: "2026-01-01", end_date: "2026-03-31" }),
                  );
                  setCreated(m);
                  await refresh();
                } catch (e) {
                  setError(errorText(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Generate demo data
            </button>
          )}
          {busy && <Busy text="Generating 10,000 synthetic rows…" />}
          {created && (
            <Notice tone="ok">
              Saved “{created.name}”.{" "}
              <Link href="/overview" style={{ fontWeight: 700 }}>
                Open overview →
              </Link>
            </Notice>
          )}
          {error && <Notice tone="error">{error}</Notice>}
        </div>
        <Link className="panel path-card" href="/data?mode=import">
          <Upload size={22} color="var(--teal)" aria-hidden="true" />
          <h3>Upload campaign CSV</h3>
          <p>Preview, map columns, check currency, dates and attribution rules, then validate before anything is saved.</p>
          <span className="btn">
            Open import <ArrowRight size={16} />
          </span>
        </Link>
        <Link className="panel path-card" href="/methodology">
          <BookOpen size={22} color="var(--peri)" aria-hidden="true" />
          <h3>Understand the workflow</h3>
          <p>How every KPI, model, Big Data comparison and budget recommendation is calculated, with formulas and limits.</p>
          <span className="btn">
            Read the methodology <ArrowRight size={16} />
          </span>
        </Link>
      </div>

      <Panel title="How a decision is made here" flat>
        <ol style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 6 }} className="muted">
          <li>
            <strong style={{ color: "var(--text)" }}>Data</strong>: synthetic demo or your authorized CSV, stored locally with provenance.
          </li>
          <li>
            <strong style={{ color: "var(--text)" }}>Measure</strong>: CTR, CPC, CPA, conversion rate and ROAS from summed totals on the server.
          </li>
          <li>
            <strong style={{ color: "var(--text)" }}>Scale</strong>: the same aggregation on 10K → 10M rows in Pandas, MapReduce and Spark.
          </li>
          <li>
            <strong style={{ color: "var(--text)" }}>Model</strong>: chronological XGBoost training that must beat a baseline before it is used.
          </li>
          <li>
            <strong style={{ color: "var(--text)" }}>Decide</strong>: your budget is split to the last paisa within your limits, and the reasons are shown.
          </li>
        </ol>
        <div className="btn-row" style={{ marginTop: 14 }}>
          <Link href="/data" className="btn sm">
            <Database size={15} /> Manage datasets
          </Link>
          <Link href="/methodology" className="btn sm ghost">
            Read the methodology
          </Link>
        </div>
      </Panel>
    </>
  );
}
