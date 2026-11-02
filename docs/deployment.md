# Deployment

## Status: NOT deployed
No Vercel/Neon/GitHub account is connected in this environment, and redistribution of the reused backend is pending the original owner's permission (see 05-risks-and-permissions.md). No deployment URL exists. Do not cite one.

## What is ready
- `frontend/vercel.json` + `frontend/api/index.py` + `frontend/scripts/prepare-backend.mjs`: the same tested Vercel-only architecture as the reference (Next.js + Python function, backend copied at build time).
- `frontend/requirements.txt` uses `xgboost-cpu` (no CUDA), no Spark/JVM.
- Production build verified locally (`npm run build`); Basic-auth guard verified on `next start` (401 without/with wrong credentials, 200 with correct; API 401 without credentials).

## Steps (when permission and accounts exist)
1. Push this repo to a **new GitHub repo you own** (private recommended).
2. Vercel → New Project → import → Root Directory `frontend`, framework Next.js, enable "Include source files outside of the Root Directory". Env: `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`.
3. Vercel Storage → create a **free** Neon Postgres; connect separate databases to Production and Preview.
4. Set `ADS_ACCESS_PASSWORD` (≥32 random characters) as a Production secret in the Vercel dashboard. Never put it in Git or chat.
5. Deploy, then verify and record in PROGRESS.md: login prompt; unauthenticated `/api/v1/workspace` → 401; generate synthetic demo; refresh persists; train (≤10,000 rows) or honest limit; PKR 1,000,000 plan exact; CSV ≤4 MiB import/export; mobile view; Big Data lab shows "Run locally".

## Hosted limits (enforced by backend)
64 MiB workspace snapshot, 4 MiB requests, training ≤10,000 rows within the request, no lab jobs, no Spark. The full lab stays local.
