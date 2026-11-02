"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, errorText, post, type Manifest, type WorkspaceState } from "@/lib/api";

export type Filters = Partial<
  Record<"start_date" | "end_date" | "platform" | "campaign" | "city" | "age" | "gender" | "device", string>
>;

type Ctx = {
  state: WorkspaceState | null;
  error: string;
  loading: boolean;
  dataset: Manifest | null;
  refresh: () => Promise<WorkspaceState | null>;
  select: (id: string | null) => Promise<void>;
  filters: Filters;
  setFilters: (f: Filters) => void;
};

const WorkspaceContext = createContext<Ctx | null>(null);

const FILTER_KEY = "signalspend.filters";

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WorkspaceState | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filters, setFiltersState] = useState<Filters>({});

  const refresh = useCallback(async () => {
    try {
      const next = await api<WorkspaceState>("/workspace");
      if (next.api_version !== "v1" || !Array.isArray(next.datasets)) {
        throw new Error("The service returned an unsupported workspace contract. Check that frontend and backend versions match.");
      }
      setState(next);
      setError("");
      return next;
    } catch (e) {
      setError(errorText(e));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Initial workspace fetch; refresh() owns its own state updates.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  // Filters are per-dataset session conveniences; the backend validates every value.
  const datasetId = state?.selected_dataset_id ?? null;
  useEffect(() => {
    let restored: Filters = {};
    try {
      const raw = sessionStorage.getItem(FILTER_KEY);
      const parsed = raw ? JSON.parse(raw) : null;
      if (parsed && parsed.dataset === datasetId) restored = parsed.filters || {};
    } catch {
      /* storage unavailable: start unfiltered */
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFiltersState(restored);
  }, [datasetId]);

  const setFilters = useCallback(
    (f: Filters) => {
      const clean = Object.fromEntries(Object.entries(f).filter(([, v]) => v)) as Filters;
      setFiltersState(clean);
      try {
        sessionStorage.setItem(FILTER_KEY, JSON.stringify({ dataset: datasetId, filters: clean }));
      } catch {
        /* ignore */
      }
    },
    [datasetId],
  );

  const select = useCallback(async (id: string | null) => {
    const next = await api<WorkspaceState>("/workspace/dataset", post({ dataset_id: id }, "PUT"));
    setState(next);
  }, []);

  const value = useMemo(
    () => ({
      state,
      error,
      loading,
      dataset: state?.selected_dataset ?? null,
      refresh,
      select,
      filters,
      setFilters,
    }),
    [state, error, loading, refresh, select, filters, setFilters],
  );
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return ctx;
}
