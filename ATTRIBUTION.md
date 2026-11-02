# Attribution and source reuse

## Reused work
**Original project:** "Advertising Budget Optimizer · Project 2" by GitHub user **adnanf787**
Repository: https://github.com/adnanf787/black-stone, commit `23e788ebfa796c83d0f21e555c61f767d55ab369` (audited 2026-11-02).

Reused in this repository:
| Path | Origin | Modified? |
|---|---|---|
| `backend/src/ads_optimizer/**` | original | Two functions changed: `benchmarks/engine_runner.py::atomic_result` (BC-1) and `benchmarks/worker.py::measure_engine` (BC-2); see docs/08-backend-change-log.md |
| `backend/tests/**` (except the new `test_windows_atomic_result.py`, `test_engine_exit_status.py`) | original | One stale date pinned in `test_schema_recognition.py` (T-1) |
| `pyproject.toml`, `requirements.lock.txt` | original | No |
| `frontend/api/index.py`, `frontend/vercel.json`, `frontend/requirements.txt`, `frontend/tsconfig.json`, `frontend/postcss.config.mjs`, `frontend/eslint.config.mjs` | original config | No |
| `frontend/proxy.ts`, `frontend/scripts/prepare-backend.mjs` | adapted from original | Realm text / comments only; same auth contract |

All algorithms (KPI maths, synthetic generator, Pandas/MapReduce/Spark benchmarks, XGBoost training and acceptance, budget optimization, commerce reconciliation, NVIDIA boundary, hosted persistence) are the original author's work.

## License status
**No license was found in the original repository.** Default copyright applies. Written permission from the owner is required before this repository (or anything containing the reused backend) is published, deployed publicly or submitted for credit.

Permission record: _not yet received_ (date / form / link to be added here).

## Original contributions in this repository (SignalSpend AI)
- Entirely new Next.js frontend: `frontend/app/**`, `frontend/components/**`, `frontend/lib/**` (typed API adapter, formatting), new visual identity and design tokens.
- New features layered on existing APIs: Welcome onboarding, Marketing performance story, Campaign funnel, Platform opportunity matrix, Data trust panel, Explain my KPI, Budget scenario review, exact-paisa verification display, University story mode with live evidence checks.
- Windows support: cross-platform launcher `scripts/dev.mjs`; BC-1/BC-2 backend fixes with regression tests.
- Commerce order/cost import wizard and comparison builder UI (`frontend/components/commerce-import.tsx`).
- QA tooling: `scripts/qa-screens.mjs`, `scripts/e2e-flows.mjs`.
- All documentation under `docs/01–08`, architecture, deployment, limitations, test report.
