"use client";

import { KeyRound, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, errorText, isAbort, post, type AIExplanation, type AIStatus, type AISummary, type ReportKind } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { Busy, LoadingPage, NeedDataset, Notice, PageHead, Panel, Segmented } from "./ui";
import { useWorkspace } from "./workspace";

export function Assistant() {
  const { dataset, loading } = useWorkspace();
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [kind, setKind] = useState<ReportKind>("performance");
  const [summary, setSummary] = useState<AISummary | null>(null);
  const [summaryError, setSummaryError] = useState("");
  const [approved, setApproved] = useState(false);
  const [key, setKey] = useState("");
  const [answer, setAnswer] = useState<AIExplanation | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const loadStatus = useCallback(async () => setStatus(await api<AIStatus>("/ai/status")), []);
  useEffect(() => {
    api<AIStatus>("/ai/status")
      .then(setStatus)
      .catch((e) => setError(errorText(e)));
  }, []);
  useEffect(() => {
    if (!dataset) return;
    const c = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setApproved(false);
    setAnswer(null);
    // Never show (or allow approving) the previous report's summary while the new one loads.
    setSummary(null);
    api<AISummary>(`/ai/summary?kind=${kind}`, { signal: c.signal })
      .then((s) => {
        setSummary(s);
        setSummaryError("");
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setSummary(null);
        setSummaryError(errorText(e));
      });
    return () => c.abort();
  }, [dataset, kind]);

  if (loading) return <LoadingPage label="Loading workspace" />;
  return (
    <>
      <PageHead eyebrow="AI insight assistant · optional" title="Explain results in plain language">
        Uses NVIDIA&apos;s hosted model only if you configure a key. It receives a short qualitative summary you approve. It never
        computes metrics, predictions or allocations, and the rest of OptiScale AI works without it.
      </PageHead>
      <div className="grid cols-2">
        <Panel
          title={
            <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
              <KeyRound size={18} color="var(--peri)" aria-hidden="true" /> Connection
            </span>
          }
        >
          {!status ? (
            <Busy text="Checking AI status…" />
          ) : (
            <div className="grid" style={{ gap: 12 }}>
              <dl className="dl">
                <dt>Provider / model</dt>
                <dd>
                  {status.provider} · <span className="mono">{status.model}</span>
                </dd>
                <dt>Key</dt>
                <dd>
                  {status.configured ? (
                    <span className="badge ok">configured ({status.key_source === "environment" ? "server environment" : "local server file"})</span>
                  ) : (
                    <span className="badge">not configured</span>
                  )}
                </dd>
                <dt>Verified</dt>
                <dd>{status.verified ? `yes · ${dateTime(status.checked_at)}` : "not yet"}</dd>
              </dl>
              {status.last_error && <Notice tone="warn">{status.last_error}</Notice>}
              {status.key_source !== "environment" && (
                <form
                  className="grid"
                  style={{ gap: 10 }}
                  onSubmit={async (e) => {
                    e.preventDefault();
                    setBusy("Saving key on the server…");
                    setError("");
                    try {
                      setStatus(await api<AIStatus>("/ai/key", post({ api_key: key }, "PUT")));
                      setKey("");
                    } catch (err) {
                      setError(errorText(err));
                    } finally {
                      setBusy("");
                    }
                  }}
                >
                  <label className="field">
                    NVIDIA API key
                    <input className="input" type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
                    <span className="hint">Sent once to your own backend and stored server-side; never shown again or placed in the browser bundle.</span>
                  </label>
                  <div className="btn-row">
                    <button className="btn" type="submit" disabled={!key || !!busy}>
                      Save key
                    </button>
                    {status.configured && (
                      <button
                        className="btn danger"
                        type="button"
                        disabled={!!busy}
                        onClick={async () => {
                          try {
                            setStatus(await api<AIStatus>("/ai/key", { method: "DELETE" }));
                          } catch (err) {
                            setError(errorText(err));
                          }
                        }}
                      >
                        <Trash2 size={14} /> Remove key
                      </button>
                    )}
                  </div>
                </form>
              )}
              {status.configured && (
                <button
                  className="btn"
                  type="button"
                  disabled={!!busy}
                  onClick={async () => {
                    setBusy("Sending a connection check (no report data)…");
                    setError("");
                    try {
                      setStatus(await api<AIStatus>("/ai/test", post({})));
                    } catch (err) {
                      setError(errorText(err));
                      await loadStatus().catch(() => undefined);
                    } finally {
                      setBusy("");
                    }
                  }}
                >
                  Test connection
                </button>
              )}
            </div>
          )}
        </Panel>
        <Panel title="Data boundary">
          <ul className="muted" style={{ margin: 0, paddingLeft: 18, fontSize: 14, display: "grid", gap: 6 }}>
            <li>Nothing is sent automatically. You see the exact outgoing summary and must approve it each time.</li>
            <li>No raw rows, customer data or full CSVs leave your machine; only the short approved summary does.</li>
            <li>Numbers in the explanation come from the summary; the reference values stay local for comparison.</li>
            <li>Synthetic sources stay labelled synthetic in the request and response.</li>
          </ul>
        </Panel>
      </div>
      {!dataset ? (
        <NeedDataset />
      ) : (
        <Panel title="Request an explanation" actions={<Segmented label="Report" value={kind} onChange={setKind} options={[{ value: "performance", label: "Performance" }, { value: "model", label: "Model" }, { value: "budget", label: "Budget plan" }]} />}>
          {summaryError && <Notice tone="warn">{summaryError}</Notice>}
          {summary && (
            <div className="grid" style={{ gap: 12 }}>
              <p className="faint" style={{ margin: 0 }}>
                {summary.scope}
              </p>
              <div>
                <div className="faint" style={{ marginBottom: 6 }}>
                  Exact outgoing summary (sha256 <span className="mono">{summary.summary_sha256.slice(0, 12)}…</span>)
                </div>
                <pre className="pre">{JSON.stringify(summary.summary, null, 2)}</pre>
              </div>
              <label className="check">
                <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />I approve sending exactly this summary to {status?.provider || "the provider"}.
              </label>
              <div className="btn-row">
                <button
                  className="btn primary"
                  type="button"
                  disabled={!approved || !status?.configured || !!busy || summary.kind !== kind}
                  onClick={async () => {
                    setBusy("Waiting for the provider…");
                    setError("");
                    try {
                      setAnswer(await api<AIExplanation>("/ai/explain", post({ kind, summary_sha256: summary.summary_sha256, approved: true })));
                    } catch (err) {
                      setError(errorText(err));
                    } finally {
                      setBusy("");
                    }
                  }}
                >
                  <Send size={15} /> Explain
                </button>
                {!status?.configured && <span className="faint">Configure a key to enable. Every other screen works without it.</span>}
              </div>
            </div>
          )}
          {busy && <Busy text={busy} />}
          {error && <Notice tone="error">{error}</Notice>}
          {answer && (
            <div className="panel flat" style={{ marginTop: 14 }}>
              <div className="eyebrow" style={{ color: "var(--peri)" }}>
                {answer.provider} · {answer.model} · {dateTime(answer.generated_at)}
              </div>
              <p style={{ whiteSpace: "pre-wrap" }}>{answer.text}</p>
              <p className="faint" style={{ margin: 0 }}>
                {answer.notice}
              </p>
            </div>
          )}
        </Panel>
      )}
    </>
  );
}
