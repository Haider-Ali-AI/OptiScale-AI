# Deployment

## Status: deployed and verified (2026-11-02)

| Item | Value |
|---|---|
| Production URL | https://optiscale-ai.vercel.app (**public demo, no login**: `ADS_PUBLIC_DEMO=1`; deletes and API-key changes refused) |
| Vercel project | `optiscale-ai` (`prj_cVY4EZgHtNtMXCf2tCE2208BTSI2`) |
| Settings | Root directory `frontend`, framework Next.js, Node 24.x, include files outside root directory = on |
| Database | Neon Postgres, **Free plan** (`free_v3`), resource `optiscale-db`, connected to **Production only** (previews never see production data) |
| Production env (names only) | `ADS_PUBLIC_DEMO=1`, `NVIDIA_API_KEY` (sensitive), `ADS_ACCESS_PASSWORD` (sensitive, used only if public demo is turned off), `ADS_ALLOWED_ORIGINS=https://optiscale-ai.vercel.app`, `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`, Neon-injected `DATABASE_URL`/`POSTGRES_URL`/… |
| Owner password | Generated locally; stored only in Vercel and in `../SIGNALSPEND-OWNER-LOGIN.txt` (outside the Git repo). Never committed |
| Deployed from | Vercel CLI (local upload), commit of this repo at deploy time; no GitHub remote is connected |
| Permission | Owner permission reported by the user on 2026-11-02 (see ATTRIBUTION.md) |

## Public demo mode (2026-11-02, user request)
Login removed: `/`, pages and APIs return 200 without credentials. DELETE requests and `/api/v1/ai/key` writes return 403; cross-site writes still return 403. Verified live. To make it private again: `vercel env rm ADS_PUBLIC_DEMO production` and redeploy (owner login returns).

Live re-test without login: browser QA 33/33 clean, core journeys 10/10, commerce 8/8, NVIDIA assistant 8/8 (real explanations for performance, model and budget reports).

## Verification evidence (production, before public mode)
| Check | Result |
|---|---|
| Unauthenticated `/`, `/overview`, `/api/v1/workspace`, `/api/v1/health` | 401 |
| Wrong password | 401 |
| Cross-origin write (`Origin: https://evil.example`) | 403 |
| Hosted notice + Postgres persistence | dataset generated, still present on the next request (new invocation) |
| Seed-42 10K synthetic generation | OK |
| XGBoost training in-request (10K rows) | succeeded, **accepted**, holdout RMSE 7,195.26 vs baseline 10,415.53 (identical to local) |
| PKR 1,000,000 plan (model) | exact Rs 1,000,000.00 (Decimal sum), identical allocation to local |
| Plan CSV export; dataset CSV export | OK (10,001 lines incl. header) |
| CSV import (500-row synthetic fixture, preview → validate → commit) | OK |
| Big Data lab | engines unavailable with "Run Big Data experiments in the local app"; UI shows "Run the lab locally" |
| Browser QA (11 routes × 375/768/1440) | all 200, 0 console errors, 0 overflow (`docs/qa-screens-dark-cloud.json`, `docs/screenshots/cloud-*`) |
| Browser journeys (`e2e-flows`) | 10/10 (`docs/e2e-flows-cloud.json`) |

Re-run against production:
```sh
APP_URL=https://optiscale-ai.vercel.app HTTP_USER=owner HTTP_PASS=<from the login file> QA_TAG=cloud node scripts/qa-screens.mjs
APP_URL=… HTTP_USER=owner HTTP_PASS=… QA_TAG=cloud node scripts/e2e-flows.mjs
```
(Git Bash on Windows: prefix with `MSYS_NO_PATHCONV=1`.)

## Redeploy
```sh
vercel deploy --prod      # from the repo root; project is linked in .vercel/
```
The first deployment of the project went straight to production (Vercel's default for a new project) before the database was attached; it was protected (401) and redeployed once Neon was connected.

## Hosted limits (enforced by backend)
64 MiB workspace snapshot, 4 MiB requests, training ≤10,000 rows within the request, no lab jobs, no Spark/JVM. The full Big Data lab runs locally. The hosted workspace is single-owner and serializes requests; it is not multi-user.

## Rotate the password
`vercel env rm ADS_ACCESS_PASSWORD production` then `vercel env add ADS_ACCESS_PASSWORD production --sensitive` (≥32 characters), then `vercel deploy --prod`. Update your private login file.
