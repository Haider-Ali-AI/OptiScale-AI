# Architecture

```
Browser ──► Next.js 16 (frontend/, port 3000)
              │  app/<route>/page.tsx → components/<screen>.tsx (client)
              │  lib/api.ts  typed adapter, fetch("/api/v1/…")
              │  proxy.ts    hosted Basic-auth guard
              ▼  next.config rewrites /api/v1/* (local)  |  vercel.json → api/index.py (hosted)
          FastAPI (backend/src/ads_optimizer, port 8000)
              ├─ data/        generator, CSV import, mapping, provenance  ──► SQLite catalog + Parquet (ADS_DATA_DIR)
              ├─ analytics/   weighted KPIs, filters, grouping
              ├─ ml/          XGBoost train/evaluate (worker process), artifacts
              ├─ optimization/ curves + exact-paisa allocation, saved plans
              ├─ benchmarks/  detached worker → one subprocess per engine (pandas | mapreduce | pyspark+JVM)
              ├─ commerce/    order/cost import, reconciliation, profit gates
              ├─ ai/          optional NVIDIA boundary (approved summaries only)
              └─ hosting/     serverless Postgres snapshot persistence
```

Principles:
- **Backend is the single source of numeric truth.** The frontend ranks, formats and converts units (paisa → PKR); it never recomputes KPIs, predictions or allocations.
- **State**: workspace selection lives on the server; per-session filters in `sessionStorage`; theme in `localStorage`. All browser storage is optional and wrapped in try/catch.
- **Long work** (training, benchmarks) is a server job polled every 1.5 s, cancellable, with terminal-status guards.
- **No large payloads**: analytics are paged server-side (≤100 groups); raw rows are previewed 20 at a time.
