"use client";

import { Check, Download, Plus, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, errorText, PLATFORMS, post, type CommerceMeta, type CommerceState, type Platform, type Row } from "@/lib/api";
import { num, shortId, today } from "@/lib/format";
import { Busy, Notice, Panel } from "./ui";
import { useWorkspace } from "./workspace";

type Profile = "shopify" | "generic" | "expenses" | "sku_costs";
type Stage = {
  token: string;
  profile: Profile;
  headers: string[];
  suggested_mapping: Record<string, string>;
  input_rows: number;
  removed_columns: number;
  fields: string[];
  notice: string;
};
type Validation = {
  can_import: boolean;
  errors: string[];
  warnings: string[];
  input_rows: number;
  orders?: number;
  line_items?: number;
  cost_rows?: number;
  duplicate_rows?: number;
  is_synthetic?: boolean;
  unknown_net_sales?: number;
  preview?: Row[];
};
type Options = {
  name: string;
  store_id: string;
  mapping: Record<string, string>;
  timezone: string;
  original_currency: string;
  exchange_rate: string;
  is_synthetic: boolean;
  confirmed: boolean;
  duplicate_policy: "reject" | "drop" | "keep";
  order_grain: "orders" | "line_items";
  discount_basis: "order_total" | "order_plus_line";
  refund_basis: "unallocated" | "merchandise_only";
  subtotal_basis: "unknown" | "before_discounts" | "after_discounts";
  snapshot_as_of: string;
  period_start: string;
  period_end: string;
  complete_export: boolean;
  refunds_verified: boolean;
  order_batch_id: string;
  cogs_basis: "sold_quantity" | "net_refunded_quantity";
};

const PROFILES: { value: Profile; label: string; example: string }[] = [
  { value: "shopify", label: "Shopify order export (line items)", example: "shopify" },
  { value: "generic", label: "Generic orders CSV", example: "generic" },
  { value: "expenses", label: "Per-order expenses (costs)", example: "expenses" },
  { value: "sku_costs", label: "SKU unit costs (COGS)", example: "sku_costs" },
];
const isCost = (p: Profile) => p === "expenses" || p === "sku_costs";

const initial = (orderBatch: string | null): Options => ({
  name: "Store orders",
  store_id: "my-store",
  mapping: {},
  timezone: "Asia/Karachi",
  original_currency: "PKR",
  exchange_rate: "",
  is_synthetic: false,
  confirmed: false,
  duplicate_policy: "reject",
  order_grain: "line_items",
  discount_basis: "order_total",
  refund_basis: "unallocated",
  subtotal_basis: "unknown",
  snapshot_as_of: today(),
  period_start: "",
  period_end: "",
  complete_export: false,
  refunds_verified: false,
  order_batch_id: orderBatch || "",
  cogs_basis: "sold_quantity",
});

/** Converts form state to the backend ImportConfig (empty optional values → null). */
function payload(o: Options, profile: Profile) {
  return {
    ...o,
    mapping: Object.fromEntries(Object.entries(o.mapping).filter(([, v]) => v)),
    exchange_rate: o.original_currency === "PKR" ? null : o.exchange_rate || null,
    period_start: o.period_start || null,
    period_end: o.period_end || null,
    order_batch_id: isCost(profile) ? o.order_batch_id || null : null,
  };
}

export function CommerceImport({ state, onSaved }: { state: CommerceState; onSaved: (m: CommerceMeta) => Promise<void> }) {
  const [profile, setProfile] = useState<Profile>("shopify");
  const [stage, setStage] = useState<Stage | null>(null);
  const [opts, setOpts] = useState<Options>(initial(state.selected_order_batch_id || state.orders[0]?.id || null));
  const [report, setReport] = useState<Validation | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<CommerceMeta | null>(null);
  const set = (c: Partial<Options>) => {
    setOpts((o) => ({ ...o, ...c, confirmed: false }));
    setReport(null);
  };

  async function upload(file?: File) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv") || file.size > 10 * 1024 * 1024) {
      setError("Choose a UTF-8 .csv file no larger than 10 MiB (4 MiB when hosted).");
      return;
    }
    setBusy("Staging the file; recognised personal fields are discarded…");
    setError("");
    setSaved(null);
    setReport(null);
    try {
      if (stage) await api(`/commerce/imports/${stage.token}`, { method: "DELETE" }).catch(() => undefined);
      const s = await api<Stage>(`/commerce/imports/preview?${new URLSearchParams({ filename: file.name, profile })}`, {
        method: "POST",
        headers: { "Content-Type": "text/csv" },
        body: file,
      });
      setStage(s);
      setOpts((o) => ({ ...o, name: file.name.replace(/\.csv$/i, "").slice(0, 100), mapping: s.suggested_mapping, confirmed: false }));
    } catch (e) {
      setStage(null);
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }

  const ex = PROFILES.find((p) => p.value === profile)!.example;
  return (
    <Panel title="Import orders or costs (CSV)" description="Preview → map → define → validate → confirm. Nothing is saved until you confirm.">
      <div className="grid" style={{ gap: 14 }}>
        <div className="form-grid">
          <label className="field">
            File type
            <select className="select" value={profile} disabled={!!stage || !!busy} onChange={(e) => setProfile(e.target.value as Profile)}>
              {PROFILES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
            <a className="hint" href={`/api/v1/commerce/examples/${ex}`} download>
              <Download size={12} /> Download a fictional example of this format
            </a>
          </label>
          <label className="field">
            CSV file
            <input className="input" type="file" accept=".csv,text/csv" disabled={!!busy} onChange={(e) => void upload(e.target.files?.[0])} />
          </label>
        </div>
        {isCost(profile) && !state.orders.length && <Notice tone="warn">Import an order snapshot first; costs attach to one order snapshot.</Notice>}
        {busy && <Busy text={busy} />}
        {error && <Notice tone="error">{error}</Notice>}
        {saved && (
          <Notice tone="ok" title={`Saved “${saved.name}”`}>
            {saved.kind} snapshot {shortId(saved.id)} · {num(saved.orders)} orders · {num(saved.cost_rows)} cost rows.
          </Notice>
        )}
        {stage && (
          <>
            <Notice tone="info" title={`${num(stage.input_rows)} rows staged · ${stage.removed_columns} personal/unused column(s) discarded`}>
              {stage.notice}
            </Notice>
            <div className="table-wrap" style={{ maxHeight: 360 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">Field</th>
                    <th scope="col">CSV column</th>
                  </tr>
                </thead>
                <tbody>
                  {stage.fields.map((f) => (
                    <tr key={f}>
                      <th scope="row">{f}</th>
                      <td>
                        <label className="sr-only" htmlFor={`cmap-${f}`}>
                          Column for {f}
                        </label>
                        <select
                          id={`cmap-${f}`}
                          className="select"
                          style={{ minHeight: 34, minWidth: 180 }}
                          value={opts.mapping[f] || ""}
                          onChange={(e) => set({ mapping: { ...opts.mapping, [f]: e.target.value } })}
                        >
                          <option value="">Not in this file</option>
                          {stage.headers.map((h) => (
                            <option key={h} value={h}>
                              {h}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="form-grid">
              <label className="field">
                Snapshot name
                <input className="input" value={opts.name} maxLength={100} onChange={(e) => set({ name: e.target.value })} />
              </label>
              {!isCost(profile) && (
                <label className="field">
                  Store namespace
                  <input className="input" value={opts.store_id} pattern="[A-Za-z0-9_-]{1,64}" onChange={(e) => set({ store_id: e.target.value })} />
                  <span className="hint">Letters, digits, - and _ only.</span>
                </label>
              )}
              {isCost(profile) && (
                <label className="field">
                  Attach to order snapshot
                  <select className="select" value={opts.order_batch_id} onChange={(e) => set({ order_batch_id: e.target.value })}>
                    <option value="">Choose…</option>
                    {state.orders.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name} · {shortId(o.id)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="field">
                Timezone (IANA)
                <input className="input" value={opts.timezone} onChange={(e) => set({ timezone: e.target.value })} />
              </label>
              <label className="field">
                Original currency
                <input className="input" maxLength={3} value={opts.original_currency} onChange={(e) => set({ original_currency: e.target.value.toUpperCase() })} />
              </label>
              {opts.original_currency !== "PKR" && (
                <label className="field">
                  Verified PKR per 1 {opts.original_currency}
                  <input className="input" inputMode="decimal" value={opts.exchange_rate} onChange={(e) => set({ exchange_rate: e.target.value.trim() })} />
                </label>
              )}
              <label className="field">
                Snapshot as of
                <input className="input" type="date" value={opts.snapshot_as_of} onChange={(e) => set({ snapshot_as_of: e.target.value })} />
              </label>
              <label className="field">
                Coverage start
                <input className="input" type="date" value={opts.period_start} onChange={(e) => set({ period_start: e.target.value })} />
              </label>
              <label className="field">
                Coverage end
                <input className="input" type="date" value={opts.period_end} onChange={(e) => set({ period_end: e.target.value })} />
              </label>
              <label className="field">
                Duplicate rows
                <select className="select" value={opts.duplicate_policy} onChange={(e) => set({ duplicate_policy: e.target.value as Options["duplicate_policy"] })}>
                  <option value="reject">Reject the file</option>
                  <option value="drop">Drop exact duplicates</option>
                  <option value="keep">Keep (they are real)</option>
                </select>
              </label>
              {!isCost(profile) && (
                <>
                  <label className="field">
                    Row grain
                    <select className="select" value={opts.order_grain} onChange={(e) => set({ order_grain: e.target.value as Options["order_grain"] })}>
                      <option value="line_items">One row per line item</option>
                      <option value="orders">One row per order</option>
                    </select>
                  </label>
                  <label className="field">
                    Discount amount covers
                    <select className="select" value={opts.discount_basis} onChange={(e) => set({ discount_basis: e.target.value as Options["discount_basis"] })}>
                      <option value="order_total">Whole order (already includes line discounts)</option>
                      <option value="order_plus_line">Order-level only; add line discounts</option>
                    </select>
                  </label>
                  <label className="field">
                    Refund amount is
                    <select className="select" value={opts.refund_basis} onChange={(e) => set({ refund_basis: e.target.value as Options["refund_basis"] })}>
                      <option value="unallocated">Unallocated (may include shipping/tax)</option>
                      <option value="merchandise_only">Merchandise only</option>
                    </select>
                  </label>
                  <label className="field">
                    Subtotal is
                    <select className="select" value={opts.subtotal_basis} onChange={(e) => set({ subtotal_basis: e.target.value as Options["subtotal_basis"] })}>
                      <option value="unknown">Not sure</option>
                      <option value="before_discounts">Before discounts</option>
                      <option value="after_discounts">After discounts</option>
                    </select>
                  </label>
                </>
              )}
              {profile === "sku_costs" && (
                <label className="field">
                  COGS basis
                  <select className="select" value={opts.cogs_basis} onChange={(e) => set({ cogs_basis: e.target.value as Options["cogs_basis"] })}>
                    <option value="sold_quantity">Sold quantity</option>
                    <option value="net_refunded_quantity">Net of refunded quantity</option>
                  </select>
                </label>
              )}
              <label className="field">
                Data origin
                <select className="select" value={String(opts.is_synthetic)} onChange={(e) => set({ is_synthetic: e.target.value === "true" })}>
                  <option value="false">Authorized merchant export</option>
                  <option value="true">Synthetic / fictional fixture</option>
                </select>
              </label>
            </div>
            {!isCost(profile) && (
              <div className="grid" style={{ gap: 8 }}>
                <label className="check">
                  <input type="checkbox" checked={opts.complete_export} onChange={(e) => set({ complete_export: e.target.checked })} />
                  This export contains every order in the coverage dates (needs both dates).
                </label>
                <label className="check">
                  <input type="checkbox" checked={opts.refunds_verified} onChange={(e) => set({ refunds_verified: e.target.checked })} />
                  I verified refund amounts against the store.
                </label>
              </div>
            )}
            <div className="btn-row">
              <button
                className="btn"
                type="button"
                disabled={!!busy}
                onClick={async () => {
                  setBusy("Validating…");
                  setError("");
                  try {
                    setReport(await api<Validation>(`/commerce/imports/${stage.token}/validate`, post(payload(opts, profile))));
                  } catch (e) {
                    setError(errorText(e));
                  } finally {
                    setBusy("");
                  }
                }}
              >
                Validate
              </button>
              <button
                className="btn ghost"
                type="button"
                onClick={async () => {
                  await api(`/commerce/imports/${stage.token}`, { method: "DELETE" }).catch(() => undefined);
                  setStage(null);
                  setReport(null);
                }}
              >
                <X size={14} /> Discard upload
              </button>
            </div>
            {report && (
              <div className="grid" style={{ gap: 10 }}>
                <div className="kpis">
                  {(
                    [
                      ["Input rows", report.input_rows],
                      ["Orders", report.orders],
                      ["Line items", report.line_items],
                      ["Cost rows", report.cost_rows],
                      ["Duplicates", report.duplicate_rows],
                      ["Unknown net sales", report.unknown_net_sales],
                    ] as [string, number | undefined][]
                  )
                    .filter(([, v]) => v != null)
                    .map(([k, v]) => (
                      <div className="kpi" key={k}>
                        <div className="kpi-label">{k}</div>
                        <div className="kpi-value">{num(v ?? null)}</div>
                      </div>
                    ))}
                </div>
                {report.errors.length > 0 && (
                  <Notice tone="error" title="Fix before importing">
                    <ul>
                      {report.errors.map((e) => (
                        <li key={e}>{e}</li>
                      ))}
                    </ul>
                  </Notice>
                )}
                {report.warnings.map((w) => (
                  <Notice tone="warn" key={w}>
                    {w}
                  </Notice>
                ))}
                {report.can_import && (
                  <>
                    <label className="check">
                      <input type="checkbox" checked={opts.confirmed} onChange={(e) => setOpts({ ...opts, confirmed: e.target.checked })} />
                      I am authorized to use this data and reviewed its definitions, currency, coverage and warnings.
                    </label>
                    <div className="btn-row">
                      <button
                        className="btn primary"
                        type="button"
                        disabled={!opts.confirmed || !!busy}
                        onClick={async () => {
                          setBusy("Saving snapshot…");
                          setError("");
                          try {
                            const m = await api<CommerceMeta>(`/commerce/imports/${stage.token}/commit`, post(payload(opts, profile)));
                            setStage(null);
                            setReport(null);
                            setSaved(m);
                            await onSaved(m);
                          } catch (e) {
                            setError(errorText(e));
                          } finally {
                            setBusy("");
                          }
                        }}
                      >
                        <Check size={15} /> Confirm and save
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}

type Mapping = { utm_source: string; utm_campaign: string; platform: Platform; campaign_id: string; account_id: string };
type Candidate = { platform: Platform; account_id: string; campaign_id: string };

export function NewComparison({ state, onCreated }: { state: CommerceState; onCreated: (id: string) => Promise<void> }) {
  const { state: ws } = useWorkspace();
  const [orderId, setOrderId] = useState(state.selected_order_batch_id || state.orders[0]?.id || "");
  const [adId, setAdId] = useState("");
  const [costIds, setCostIds] = useState<string[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [windowDays, setWindowDays] = useState(7);
  const [maturity, setMaturity] = useState(30);
  const [shipping, setShipping] = useState(false);
  const [refSales, setRefSales] = useState("");
  const [refOrders, setRefOrders] = useState("");
  const [maps, setMaps] = useState<Mapping[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [confirm, setConfirm] = useState({ scope: false, tz: false, maps: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const order = state.orders.find((o) => o.id === orderId);
  useEffect(() => {
    if (!order) return;
    // Default the comparison window to the order snapshot's coverage.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStart(order.period_start || "");
    setEnd(order.period_end || "");
  }, [order]);
  useEffect(() => {
    if (!adId) return;
    api<{ campaigns: Candidate[] }>(`/commerce/campaigns/${adId}`)
      .then((r) => setCandidates(r.campaigns))
      .catch(() => setCandidates([]));
  }, [adId]);

  if (!state.orders.length) return null;
  const costs = state.costs.filter((c) => !orderId || c.order_batch_id === orderId);
  return (
    <Panel title="Create a comparison" description="Compare one order snapshot with a separately selected ad dataset. Only exact, evidenced UTM mappings count as matches.">
      <form
        className="grid"
        style={{ gap: 14 }}
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            const r = await api<{ manifest: CommerceMeta }>(
              "/commerce/reconciliations",
              post({
                order_batch_id: orderId,
                ad_dataset_id: adId,
                cost_batch_ids: costIds,
                start_date: start,
                end_date: end,
                ad_scope_confirmed: confirm.scope,
                timezones_confirmed: confirm.tz,
                mappings_confirmed: confirm.maps,
                mappings: maps,
                attribution_window_days: windowDays,
                maturity_days: maturity,
                include_shipping_income: shipping,
                reference_net_sales: refSales || null,
                reference_eligible_orders: refOrders ? Number(refOrders) : null,
              }),
            );
            await onCreated(r.manifest.id);
          } catch (err) {
            setError(errorText(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="form-grid">
          <label className="field">
            Order snapshot
            <select className="select" value={orderId} onChange={(e) => setOrderId(e.target.value)}>
              {state.orders.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name} · {num(o.orders)} orders {o.is_synthetic ? "· fictional" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Ad campaign dataset
            <select className="select" required value={adId} onChange={(e) => setAdId(e.target.value)}>
              <option value="">Choose…</option>
              {ws?.datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} · {d.date_start}→{d.date_end}
                </option>
              ))}
            </select>
            <span className="hint">Does not change your selected analytics source.</span>
          </label>
          <label className="field">
            Start
            <input className="input" type="date" required value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="field">
            End
            <input className="input" type="date" required value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <label className="field">
            Attribution window (days)
            <input className="input" type="number" min={0} max={90} value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))} />
          </label>
          <label className="field">
            Maturity (days)
            <input className="input" type="number" min={0} max={90} value={maturity} onChange={(e) => setMaturity(Number(e.target.value))} />
          </label>
          <label className="field">
            Reference net sales (PKR, optional)
            <input className="input" inputMode="decimal" value={refSales} onChange={(e) => setRefSales(e.target.value.trim())} />
          </label>
          <label className="field">
            Reference eligible orders (optional)
            <input className="input" type="number" min={0} value={refOrders} onChange={(e) => setRefOrders(e.target.value)} />
          </label>
        </div>
        {costs.length > 0 && (
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="field" style={{ marginBottom: 6 }}>
              Cost snapshots for this order snapshot
            </legend>
            <div className="btn-row">
              {costs.map((c) => (
                <label className="check" key={c.id}>
                  <input
                    type="checkbox"
                    checked={costIds.includes(c.id)}
                    onChange={(e) => setCostIds(e.target.checked ? [...costIds, c.id] : costIds.filter((x) => x !== c.id))}
                  />
                  {c.name} · {num(c.cost_rows)} rows
                </label>
              ))}
            </div>
          </fieldset>
        )}
        <div>
          <div className="btn-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <strong>UTM → campaign mappings</strong>
            <button
              className="btn sm"
              type="button"
              onClick={() => setMaps([...maps, { utm_source: "", utm_campaign: "", platform: candidates[0]?.platform || "Facebook", campaign_id: candidates[0]?.campaign_id || "", account_id: candidates[0]?.account_id || "" }])}
            >
              <Plus size={14} /> Add mapping
            </button>
          </div>
          {maps.length === 0 && <p className="faint">Optional. Orders that carry campaign identifiers can match without mappings; UTM-only orders need one.</p>}
          {maps.map((m, i) => {
            const upd = (c: Partial<Mapping>) => setMaps(maps.map((x, j) => (j === i ? { ...x, ...c } : x)));
            return (
              <div key={i} className="form-grid" style={{ alignItems: "end", marginBottom: 8 }}>
                <label className="field">
                  utm_source
                  <input className="input" required value={m.utm_source} onChange={(e) => upd({ utm_source: e.target.value })} />
                </label>
                <label className="field">
                  utm_campaign
                  <input className="input" required value={m.utm_campaign} onChange={(e) => upd({ utm_campaign: e.target.value })} />
                </label>
                <label className="field">
                  Ad campaign
                  <select
                    className="select"
                    value={`${m.platform}|${m.account_id}|${m.campaign_id}`}
                    onChange={(e) => {
                      const [platform, account_id, campaign_id] = e.target.value.split("|");
                      upd({ platform: platform as Platform, account_id, campaign_id });
                    }}
                  >
                    {!candidates.some((c) => c.campaign_id === m.campaign_id) && <option value={`${m.platform}||${m.campaign_id}`}>Choose an ad dataset campaign…</option>}
                    {candidates.map((c) => (
                      <option key={`${c.platform}|${c.account_id}|${c.campaign_id}`} value={`${c.platform}|${c.account_id}|${c.campaign_id}`}>
                        {c.platform} · {c.campaign_id} {c.account_id ? `(${c.account_id})` : ""}
                      </option>
                    ))}
                    {!candidates.length && PLATFORMS.map((p) => <option key={p} disabled>{p}: select an ad dataset first</option>)}
                  </select>
                </label>
                <button className="btn sm danger" type="button" aria-label="Remove mapping" onClick={() => setMaps(maps.filter((_, j) => j !== i))}>
                  <Trash2 size={14} />
                </button>
              </div>
            );
          })}
        </div>
        <div className="grid" style={{ gap: 8 }}>
          <label className="check">
            <input type="checkbox" checked={confirm.scope} onChange={(e) => setConfirm({ ...confirm, scope: e.target.checked })} />
            The ad dataset covers the same store and all its paid campaigns for these dates.
          </label>
          <label className="check">
            <input type="checkbox" checked={confirm.tz} onChange={(e) => setConfirm({ ...confirm, tz: e.target.checked })} />
            Order and ad report timezones are comparable.
          </label>
          <label className="check">
            <input type="checkbox" checked={confirm.maps} onChange={(e) => setConfirm({ ...confirm, maps: e.target.checked })} />
            The mappings above (if any) are verified merchant UTM conventions.
          </label>
          <label className="check">
            <input type="checkbox" checked={shipping} onChange={(e) => setShipping(e.target.checked)} />
            Include shipping income in contribution.
          </label>
        </div>
        <div className="btn-row">
          <button className="btn primary" type="submit" disabled={busy || !orderId || !adId || !start || !end}>
            Save comparison
          </button>
        </div>
        {busy && <Busy text="Reconciling orders with ad observations…" />}
        {error && <Notice tone="error">{error}</Notice>}
      </form>
    </Panel>
  );
}
