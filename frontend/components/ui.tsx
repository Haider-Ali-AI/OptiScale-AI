"use client";

import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";
import type { Manifest } from "@/lib/api";
import { sourceKind } from "@/lib/format";

export const PLATFORM_COLOR: Record<string, string> = {
  Facebook: "var(--p-facebook)",
  Instagram: "var(--p-instagram)",
  Google: "var(--p-google)",
  TikTok: "var(--p-tiktok)",
  YouTube: "var(--p-youtube)",
};
/** Distinguishes series beyond colour (WCAG 1.4.1). */
export const PLATFORM_SHAPE: Record<string, "circle" | "square" | "diamond" | "triangle" | "cross"> = {
  Facebook: "circle",
  Instagram: "diamond",
  Google: "square",
  TikTok: "triangle",
  YouTube: "cross",
};

export function Marker({ platform, size = 10 }: { platform: string; size?: number }) {
  const color = PLATFORM_COLOR[platform] || "var(--text-3)";
  const shape = PLATFORM_SHAPE[platform] || "circle";
  const s = size;
  return (
    <svg width={s} height={s} viewBox="0 0 10 10" aria-hidden="true" style={{ flex: "none" }}>
      {shape === "circle" && <circle cx="5" cy="5" r="4.5" fill={color} />}
      {shape === "square" && <rect x="0.5" y="0.5" width="9" height="9" fill={color} />}
      {shape === "diamond" && <path d="M5 0 10 5 5 10 0 5Z" fill={color} />}
      {shape === "triangle" && <path d="M5 0.5 9.8 9.5H0.2Z" fill={color} />}
      {shape === "cross" && <path d="M3.5 0h3v3.5H10v3H6.5V10h-3V6.5H0v-3h3.5Z" fill={color} />}
    </svg>
  );
}

export function PlatformLabel({ name }: { name: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <Marker platform={name} />
      {name}
    </span>
  );
}

export function PageHead({
  eyebrow,
  title,
  children,
  actions,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div style={{ minWidth: 0 }}>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {actions && <div className="btn-row">{actions}</div>}
    </header>
  );
}

export function Panel({
  title,
  description,
  actions,
  children,
  flat,
  id,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flat?: boolean;
  id?: string;
}) {
  return (
    <section className={`panel${flat ? " flat" : ""}`} id={id} aria-label={typeof title === "string" ? title : undefined}>
      {(title || actions) && (
        <div className="panel-head">
          <div style={{ minWidth: 0 }}>
            {title && <h2 className="section">{title}</h2>}
            {description && <p>{description}</p>}
          </div>
          {actions && <div className="btn-row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warn" | "error" | "ok";
  title?: string;
  children?: ReactNode;
}) {
  const Icon = tone === "error" ? XCircle : tone === "warn" ? AlertTriangle : tone === "ok" ? CheckCircle2 : Info;
  const color =
    tone === "error" ? "var(--critical)" : tone === "warn" ? "var(--amber)" : tone === "ok" ? "var(--ok)" : "var(--peri)";
  return (
    <div className={`notice ${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon size={17} color={color} aria-hidden="true" />
      <div style={{ minWidth: 0 }}>
        {title && <strong style={{ display: "block" }}>{title}</strong>}
        {children}
      </div>
    </div>
  );
}

export function Busy({ text }: { text: string }) {
  return (
    <div className="notice" role="status" aria-live="polite">
      <Loader2 size={17} className="spin" color="var(--teal)" aria-hidden="true" />
      <span>{text}</span>
    </div>
  );
}

export function Skeleton({ height = 120 }: { height?: number }) {
  return <div className="skeleton" style={{ height }} aria-hidden="true" />;
}

export function LoadingPage({ label }: { label: string }) {
  return (
    <div className="grid" aria-busy="true">
      <span className="sr-only" role="status">
        {label}
      </span>
      <Skeleton height={64} />
      <Skeleton height={92} />
      <div className="grid cols-2">
        <Skeleton height={260} />
        <Skeleton height={260} />
      </div>
    </div>
  );
}

export function Empty({
  title,
  children,
  action,
  icon,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty">
      {icon}
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function NeedDataset() {
  return (
    <Empty title="Select or create a campaign dataset first">
      This view reads the backend aggregates of one selected dataset. Generate a labelled synthetic demo or import an
      authorized campaign CSV in Data Studio.
      <span style={{ display: "block", marginTop: 12 }}>
        <Link className="btn primary" href="/data">
          Open Data Studio
        </Link>
      </span>
    </Empty>
  );
}

export function SourceBadge({ dataset }: { dataset: Manifest }) {
  const synthetic = dataset.is_synthetic;
  return (
    <span className={`badge ${synthetic ? "amber" : "teal"}`} title={synthetic ? "Simulated data — not business performance" : "Authorized advertiser export"}>
      {sourceKind(dataset)}
    </span>
  );
}

export function Kpi({
  label,
  value,
  sub,
  na,
  help,
}: {
  label: string;
  value: string;
  sub?: string;
  na?: boolean;
  help?: string;
}) {
  return (
    <div className="kpi">
      <div className="kpi-label">
        {label}
        {help && (
          <span className="faint" title={help} aria-label={`${label}: ${help}`} tabIndex={0} style={{ cursor: "help" }}>
            ⓘ
          </span>
        )}
      </div>
      <div className={`kpi-value${na ? " na" : ""}`}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Native <dialog> confirm; focus is trapped by the browser and Escape closes it. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  onConfirm,
  onClose,
  busy,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="modal" onClose={onClose} aria-labelledby="confirm-title">
      <h2 id="confirm-title" className="section" style={{ marginBottom: 10 }}>
        {title}
      </h2>
      <div className="muted" style={{ fontSize: 14 }}>
        {children}
      </div>
      <div className="btn-row" style={{ marginTop: 18, justifyContent: "flex-end" }}>
        <button className="btn ghost" type="button" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button className="btn danger" type="button" onClick={onConfirm} disabled={busy}>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div className="faint">{label}</div>
      <div className="num" style={{ fontWeight: 750, overflowWrap: "anywhere" }}>
        {value}
      </div>
    </div>
  );
}
