# 01 · Source audit (Phase 0)

Audited 2026-11-02 on Windows 11 (Python 3.12.15, Node 24.14.1).

## Reference repository

| Item | Value |
|---|---|
| Remote | https://github.com/adnanf787/black-stone.git |
| Branch | `main` (only branch) |
| HEAD | `23e788ebfa796c83d0f21e555c61f767d55ab369` ("Package Python backend inside Vercel deployment root") |
| Local status after clone | clean; protected locally with tag `baseline-audit-2026-11-02` (not pushed) |
| Tracked files | 290 (backend 74, frontend 34, docs ~150 incl. screenshots/evidence JSON, scripts 19) |
| License | **No LICENSE file and no license statement anywhere in the repository.** See 05-risks-and-permissions.md |
| Local copy | `../reference-source/` — untouched read-only reference |

The public snapshot is what was audited; no other working tree was available.

## Stack actually present (verified in source, not only README)

- **Backend** `backend/src/ads_optimizer/` (≈7.2k lines Python): FastAPI 0.162, Pydantic 2, pandas 2.3, pyarrow, XGBoost 3.4, scikit-learn, SciPy (HiGHS LP for concave curves), psutil, optional PySpark 4.2, optional psycopg (hosted snapshots). SQLite catalog + Parquet files under `ADS_DATA_DIR` (default `./data`).
- **Frontend** `frontend/` (≈9.4k lines TSX): Next.js 16.4, React 19.3, Tailwind 4, Recharts 3, Radix Dialog, lucide. Single dynamic route `app/[section]` rendering one large `Workspace` component; light lime/charcoal "Adwise" bento identity.
- **Hosting**: `frontend/api/index.py` imports the backend copied at build time (`frontend/scripts/prepare-backend.mjs`) into `.backend/src`; `frontend/vercel.json` routes `/api/v1/*` to that Python function; `frontend/proxy.ts` + backend middleware enforce single-owner Basic auth (`owner` / `ADS_ACCESS_PASSWORD` ≥ 32 chars); `hosting/workspace.py` persists the whole workspace as a Postgres snapshot per request.
- **Scripts**: `scripts/dev.mjs` (macOS/Linux only: hardcodes `.venv/bin/python`), `verify.mjs`, `benchmark_phase2.py`, `demo_phase5.py`, ten Playwright browser scripts.

## Feature status (code-level classification)

| Feature | Status | Evidence |
|---|---|---|
| Seeded synthetic campaign generator (100–10,000 rows, 5 platforms, all 12 fields) | **Working** | `data/synthetic_generator.py`; generated seed-42 10K via API on Windows |
| CSV preview → mapping → validation → commit, profiles generic/meta/google/tiktok | **Working** | `data/csv_importer.py`, `schema_mapping.py`; tests pass |
| Weighted KPI analytics + filters + grouping/sort/paging + CSV export (formula-injection safe) | **Working** | `analytics/metrics.py`; verified totals via API |
| Big Data lab: 10K–10M generation, Pandas / local MapReduce / local PySpark, ≥3 repeats, parity check | **Working (Pandas, MapReduce)**, **Spark blocked on Java** in this environment; **Windows defect found** (see 08-backend-change-log.md) | `benchmarks/*`; real runs on this machine |
| XGBoost revenue model, chronological split, baseline, acceptance gate, artifact reload | **Working** | trained via API: accepted, holdout RMSE 7,195 vs baseline 10,416 |
| Budget optimizer: auto/model/baseline/historical/evidence, exact paisa, limits, comparisons, exports | **Working** | PKR 1,000,000 plan totals exactly (browser + independent sum) |
| Commerce CSV pilot: orders/costs import, reconciliation, gated contribution plan | **Working (fixtures)**; real merchant validation **Not Verified** | pilot demo via API |
| NVIDIA explanation assistant | **Partially verifiable**: status/preview/approval flows work; live provider call **Not Verified** (no key supplied) | `ai/*` |
| Live ad/Shopify connectors (Phase 7), SaaS (Phase 8) | **Planned** (not implemented) | capability `connections` = unavailable |
| Vercel hosted mode | **Not Verified** (no deployment evidence in repo beyond docs; no accounts here) | `docs/vercel.md` |

## Existing UI inventory (reference, replaced)

Routes: `/` (overview), `/data-studio`, `/campaigns`, `/ml-studio`, `/budget-optimizer`, `/big-data-lab`, `/ai-assistant`, `/commerce`, `/help`. All rendered by one `Workspace` client component. SignalSpend keeps every legacy path working via redirects (see 07-ui-journeys.md).

## Data contracts reused unchanged

All 54 `/api/v1` routes (see 03-api-contract-inventory.md), Pydantic models in `domain.py`, `schemas.py`, `*/contracts.py`. The new frontend only consumes them through `frontend/lib/api.ts`.
