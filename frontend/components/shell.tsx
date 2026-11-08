"use client";

import {
  BarChart3,
  BookOpen,
  BrainCircuit,
  Compass,
  Cpu,
  Database,
  LayoutDashboard,
  Menu,
  Moon,
  ShoppingBag,
  Sparkles,
  Sun,
  Table2,
  Target,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { errorText } from "@/lib/api";
import { Notice, SourceBadge } from "./ui";
import { useWorkspace, WorkspaceProvider } from "./workspace";

export const NAV = [
  {
    label: "Start",
    items: [
      { href: "/", label: "Welcome", icon: Compass },
    ],
  },
  {
    label: "Analyse",
    items: [
      { href: "/overview", label: "Executive overview", icon: LayoutDashboard },
      { href: "/campaigns", label: "Campaign explorer", icon: Table2 },
      { href: "/data", label: "Data studio", icon: Database },
    ],
  },
  {
    label: "Decide",
    items: [
      { href: "/budget", label: "Budget decision studio", icon: Target },
      { href: "/models", label: "ML validation studio", icon: BrainCircuit },
      { href: "/lab", label: "Big Data lab", icon: Cpu },
    ],
  },
  {
    label: "Extend",
    items: [
      { href: "/commerce", label: "Commerce & attribution", icon: ShoppingBag },
      { href: "/assistant", label: "AI insight assistant", icon: Sparkles },
      { href: "/methodology", label: "Methodology & help", icon: BookOpen },
    ],
  },
];

const ALL = NAV.flatMap((g) => g.items);

function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light" | null>(null);
  useEffect(() => {
    // Read the theme the pre-paint script applied.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme((document.documentElement.dataset.theme as "dark" | "light") || "dark");
  }, []);
  const next = theme === "light" ? "dark" : "light";
  return (
    <button
      type="button"
      className="btn ghost sm"
      aria-label={`Switch to ${next} theme`}
      onClick={() => {
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem("optiscale.theme", next);
        } catch {
          /* preference not persisted */
        }
        setTheme(next);
      }}
    >
      {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
      <span className="sr-only">Theme</span>
    </button>
  );
}

function SourcePicker() {
  const { state, select, refresh } = useWorkspace();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!state) return null;
  if (!state.datasets.length)
    return (
      <Link href="/data" className="btn sm">
        <Database size={15} /> Add data
      </Link>
    );
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      {state.selected_dataset && <SourceBadge dataset={state.selected_dataset} />}
      <label className="sr-only" htmlFor="source-picker">
        Selected campaign source
      </label>
      <select
        id="source-picker"
        className="select"
        style={{ minHeight: 34, maxWidth: 260, fontSize: 13 }}
        value={state.selected_dataset_id ?? ""}
        disabled={busy}
        onChange={async (e) => {
          setBusy(true);
          setError("");
          try {
            await select(e.target.value || null);
          } catch (err) {
            setError(errorText(err));
            await refresh();
          } finally {
            setBusy(false);
          }
        }}
      >
        <option value="">No source selected</option>
        {state.datasets.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name} · {d.rows.toLocaleString("en-PK")} rows
          </option>
        ))}
      </select>
      {error && (
        <span role="alert" className="badge critical" title={error}>
          Selection failed
        </span>
      )}
    </div>
  );
}

function Frame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { state, error, loading, refresh } = useWorkspace();
  const current = ALL.find((i) => (i.href === "/" ? pathname === "/" : pathname.startsWith(i.href)));
  useEffect(() => {
    // Close the mobile navigation after route changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpen(false);
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <div className="shell">
      <nav className="rail" data-open={open} aria-label="Primary">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Link href="/" className="brand">
            <span className="brand-mark" aria-hidden="true">
              O
            </span>
            <span className="brand-name">
              OptiScale AI
              <small>Scalable Optimization Engine</small>
            </span>
          </Link>
          <button className="btn ghost sm menu-toggle" type="button" aria-label="Close navigation" onClick={() => setOpen(false)} style={{ color: "#fff" }}>
            <X size={18} />
          </button>
        </div>
        {NAV.map((group) => (
          <div className="nav-group" key={group.label}>
            <div className="nav-label">{group.label}</div>
            {group.items.map(({ href, label, icon: Icon }) => (
              <Link key={href} href={href} className="nav-link" aria-current={current?.href === href ? "page" : undefined}>
                <Icon size={17} aria-hidden="true" />
                {label}
              </Link>
            ))}
          </div>
        ))}
        <div className="rail-foot">
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <BarChart3 size={13} aria-hidden="true" />
            {state?.hosting_notice ? "Hosted single-owner mode" : "Local single-user mode"}
          </div>
          <div>No ad or store accounts connected.</div>
        </div>
      </nav>
      <div className="main">
        <header className="topbar">
          <button className="btn ghost sm menu-toggle" type="button" aria-label="Open navigation" aria-expanded={open} onClick={() => setOpen(true)}>
            <Menu size={18} />
          </button>
          <div className="crumbs" aria-label="Breadcrumb">
            <span>OptiScale</span>
            <span aria-hidden="true">/</span>
            <strong aria-current="page">{current?.label || "Page"}</strong>
          </div>
          <div className="topbar-right">
            <SourcePicker />
            <ThemeToggle />
          </div>
        </header>
        <main className="content" id="main">
          {state?.hosting_notice && <Notice tone="info">{state.hosting_notice}</Notice>}
          {error && !loading && (
            <Notice tone="error" title="Backend unavailable">
              {error}{" "}
              <button className="btn sm" type="button" onClick={() => void refresh()} style={{ marginTop: 8 }}>
                Retry connection
              </button>
            </Notice>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <WorkspaceProvider>
      <Frame>{children}</Frame>
    </WorkspaceProvider>
  );
}
