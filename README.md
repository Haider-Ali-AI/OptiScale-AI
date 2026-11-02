# SignalSpend AI: Marketing Intelligence & Budget Optimization Studio

**Project 2 · Digital Advertising Budget Optimizer.** *Where should a company spend the next Rs 1 million across Facebook, Instagram, Google, TikTok and YouTube?*

SignalSpend AI is a decision studio for students, marketers and small teams. It turns campaign history into weighted KPIs, measures Pandas vs MapReduce vs Spark on 10K–10M rows, trains and validates an XGBoost revenue model, and allocates a user-entered PKR budget exactly to the paisa within the user's limits, with every method, caveat and data source labelled.

> **Provenance.** The Python/FastAPI backend is reused from [adnanf787/black-stone](https://github.com/adnanf787/black-stone) (commit `23e788e`) with two documented, test-first benchmark fixes. The frontend, design system, QA scripts and documentation in this repository are new. See [ATTRIBUTION.md](ATTRIBUTION.md). Reuse and deployment permission was granted by the owner (recorded 2026-11-02).

![Executive overview](docs/screenshots/overview-1440.png)

## What works (verified 2026-11-02 on Windows 11)
| Area | Status |
|---|---|
| Synthetic seeded demo + authorized CSV import (preview → map → validate → confirm) | ✅ |
| Weighted KPIs (CTR, CPC, CPA, CVR, ROAS, revenue), filters, grouping, exports | ✅ |
| Big Data lab: Pandas, local MapReduce and local Spark at 10K / 100K / 1M / 10M, 3 repeats each, all parity-correct | ✅ (Spark needs Java 17/21/25, see setup) |
| XGBoost model: chronological split, baseline, acceptance gate, re-evaluation | ✅ |
| Budget engine: PKR 1,000,000 exact-paisa plan, constraints, comparisons, CSV/JSON | ✅ |
| Commerce: import own order/cost CSVs, UTM mappings, comparisons, gated contribution plans | ✅ (UI-tested with fictional fixtures; real merchant validation pending) |
| NVIDIA explanation assistant (optional) | UI ready; live provider not verified (no key) |
| Vercel deployment (private, Neon Postgres) | ✅ https://signalspend-ai.vercel.app, verified: auth, persistence, training, PKR 1M plan, CSV, browser QA ([deployment](docs/deployment.md)) |

No ad or store accounts are connected, and nothing changes live spending.

## Screens
Welcome · University story · Executive overview · Campaign explorer · Data studio · Budget decision studio · ML validation studio · Big Data lab · Commerce & attribution · AI insight assistant · Methodology & help. Old reference URLs (`/data-studio`, `/budget-optimizer`, `/ml-studio`, `/big-data-lab`, `/ai-assistant`, `/help`) redirect.

## Setup

Requirements: Node ≥ 20.9, Python 3.11–3.12, optional JDK 17/21/25 for Spark.

### Windows (PowerShell)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock.txt
.\.venv\Scripts\python -m pip install --no-deps -e .
npm --prefix frontend ci
npm run dev
```
For Spark, unzip a Temurin JDK 17 (https://adoptium.net) into `.runtime\` (e.g. `.runtime\jdk-17.0.x+y\`) or set `$env:JAVA_HOME`. `npm run dev` detects it automatically.

### macOS / Linux / WSL2
```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install --no-deps -e .
npm --prefix frontend ci
npm run dev
```

Open http://127.0.0.1:3000 (API docs at http://127.0.0.1:8000/docs). For a throwaway workspace set `ADS_DATA_DIR` (PowerShell: `$env:ADS_DATA_DIR="C:\temp\ss-data"`) before `npm run dev`.

## Checks
```sh
python -m pytest -q            # backend (use .venv's python)
python -m ruff check backend scripts
npm run check                  # tsc + eslint
npm run build                  # production build
npm run test:ui                # 11 routes × 7 widths: status, console errors, overflow, screenshots
npm run test:e2e               # real browser journeys incl. PKR 1M exact plan
npm run test:e2e:commerce      # order/cost CSV import + comparison through the UI
```
The browser scripts use installed Microsoft Edge (`PW_CHANNEL=chrome` or `CHROMIUM_EXECUTABLE=…` to change). Results: [docs/test-report.md](docs/test-report.md).

## Reproduce the academic demo
1. Welcome → **Generate demo data** (seed 42, 10,000 rows, 2026-01-01 → 2026-03-31).
2. ML validation studio → as-of **2026-10-29**, lag 0 → **Train revenue model**.
3. Budget decision studio → **1000000**, Automatic, 0–100% → **Generate recommendation** → export.
4. Big Data lab → each scale 10K → 10M, engines Pandas/MapReduce/Spark → **Start benchmark** → export JSON/CSV.
Full script: [University story](docs/07-ui-journeys.md) and in-app `/story`.

## Documentation
[Source audit](docs/01-source-audit.md) · [Assignment matrix](docs/02-assignment-compliance-matrix.md) · [API inventory](docs/03-api-contract-inventory.md) · [Test baseline](docs/04-test-baseline.md) · [Risks & permissions](docs/05-risks-and-permissions.md) · [Design system](docs/06-design-system.md) · [UI journeys](docs/07-ui-journeys.md) · [Backend change log](docs/08-backend-change-log.md) · [Architecture](docs/architecture.md) · [Deployment](docs/deployment.md) · [Limitations](docs/limitations.md) · [Progress](docs/PROGRESS.md)

## Troubleshooting
- *Backend unavailable* banner → backend not on :8000; run `npm run dev` from the repo root.
- Spark "unavailable" → no compatible Java; see setup. Pandas and MapReduce still run.
- Port busy → stop the other process; the frontend proxy always targets :8000 unless `API_ORIGIN` is set.
