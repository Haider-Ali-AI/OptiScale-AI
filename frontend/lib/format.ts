import type { Manifest } from "./api";

export const NA = "Not available";

const nf = (digits: number) => new Intl.NumberFormat("en-PK", { maximumFractionDigits: digits });

export const num = (v: number | null | undefined, digits = 0) => (v == null ? NA : nf(digits).format(v));

/** PKR with paisa precision. Display only — totals come from the backend. */
export const pkr = (v: number | null | undefined, digits = 2) =>
  v == null
    ? NA
    : `Rs ${new Intl.NumberFormat("en-PK", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v)}`;

export const pkrShort = (v: number | null | undefined) => {
  if (v == null) return NA;
  const abs = Math.abs(v);
  if (abs >= 1e7) return `Rs ${(v / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `Rs ${(v / 1e5).toFixed(2)} Lakh`;
  return pkr(v, abs >= 1000 ? 0 : 2);
};

export const compact = (v: number | null | undefined) =>
  v == null ? NA : new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v);

export const pct = (v: number | null | undefined, digits = 2) => (v == null ? NA : `${nf(digits).format(v)}%`);

export const ratio = (v: number | null | undefined, digits = 2) => (v == null ? NA : `${nf(digits).format(v)}×`);

/** Coverage never rounds a partial value up to 100%. */
export const coverage = (r: number | null | undefined) =>
  r == null ? NA : r === 1 ? "100%" : `${nf(1).format(Math.floor(r * 1000) / 10)}%`;

export const bytes = (v: number | null | undefined) =>
  v == null
    ? "Not measured"
    : v >= 1024 ** 3
      ? `${(v / 1024 ** 3).toFixed(1)} GiB`
      : `${(v / 1024 ** 2).toFixed(1)} MiB`;

export const secs = (v: number | null | undefined) =>
  v == null ? "Not measured" : v < 1 ? `${(v * 1000).toFixed(1)} ms` : `${v.toFixed(3)} s`;

export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : NA;

export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export const sourceKind = (m: Manifest) =>
  m.source === "synthetic_csv" ? "Synthetic CSV" : m.is_synthetic ? "Synthetic demo" : "Advertiser CSV";

export const engineName = (id: string) =>
  ({ pandas: "Pandas", mapreduce: "Local MapReduce", spark: "Apache Spark (local)" })[id] || id;

export const shortId = (id: string) => id.slice(0, 8);
