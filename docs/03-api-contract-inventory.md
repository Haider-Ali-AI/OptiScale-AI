# 03 · API contract inventory

Base path `/api/v1`. All routes are served by the unchanged `ads_optimizer.api:app`. Errors: `{"detail": string}` (DomainError → its status; validation → 422). Every response sets `Cache-Control: no-store`.

**Cross-cutting middleware (`local_write_guard`)**
- Hosted (`ADS_HOSTED=1`, Vercel, or password set): every route except `/health` requires `Authorization: Basic owner:<ADS_ACCESS_PASSWORD>` (≥32 chars) → else 401/503.
- Writes (POST/PUT/DELETE/PATCH): `Origin` must be an allowed app origin; `Sec-Fetch-Site: cross-site` rejected (403); body ≤ 10 MiB local / 4 MiB hosted (413).
- Serverless: request runs inside a Postgres-locked workspace snapshot restore/commit.

| Method & path | Request | Response | SignalSpend screen |
|---|---|---|---|
| GET `/health` | — | `{status, service, version}` | launcher |
| GET `/workspace` | — | `WorkspaceState` | shell (source picker, trust panel) |
| PUT `/workspace/dataset` | `{dataset_id \| null}` | `WorkspaceState` | shell, Data studio |
| POST `/datasets/generate` | `GenerateConfig` (rows 100–10,000, seed, dates 7–366 d, platforms) | `DatasetManifest` 201 | Welcome, Data studio |
| GET `/datasets/{id}/preview` | `page, page_size≤100` | `{columns, rows, total, page, page_size}` | Data studio |
| DELETE `/datasets/{id}` | — | `{deleted}` (cascades models/plans) | Data studio |
| GET `/datasets/{id}/analytics` | filters `start_date,end_date,platform,campaign,city,age,gender,device`; `group_by, page, page_size≤100, sort, direction` | `{dataset, totals, platforms, trend, trend_grain, group_by, table, table_total, …}` | Overview, Campaigns, Methodology |
| GET `/datasets/{id}/export` | same filters | streamed CSV with provenance columns | Overview, Campaigns, Data studio |
| POST `/imports/preview` | raw CSV body; `filename, profile∈{generic,meta,google,tiktok}` | `Stage` | Data studio |
| POST `/imports/{token}/validate` | `ImportOptions` | `ValidationReport` | Data studio |
| POST `/imports/{token}/commit` | `ImportOptions` (`confirmed=true`) | `DatasetManifest` 201 | Data studio |
| DELETE `/imports/{token}` | — | `{discarded}` | Data studio |
| GET `/templates/campaign.csv` | — | 100-row synthetic CSV | Data studio |
| GET `/lab` | — | `{environment, methodology, datasets, jobs}` | Big Data lab, Story |
| POST `/lab/jobs` | `ExperimentConfig` (rows ∈ {1e4,1e5,1e6,1e7}, engines, repeats 3–7, workers 1–4, memory 512–4096) | `LabJob` 202 | Big Data lab |
| GET `/lab/jobs/{id}` | — | `LabJob` (polled) | Big Data lab |
| POST `/lab/jobs/{id}/cancel` | — | `LabJob` | Big Data lab |
| GET `/lab/jobs/{id}/export` | `format=json\|csv` | file | Big Data lab |
| GET `/lab/datasets/{id}/preview` | — | first 20 rows | (API only) |
| DELETE `/lab/datasets/{id}` | — | `{deleted}` | Big Data lab |
| GET `/ml` | — | `{jobs (selected source), active_job, versions}` | ML studio |
| POST `/ml/readiness` | `TrainingConfig` | `{ready, reasons, coverage, splits, reporting_setup}` | ML studio |
| POST `/datasets/{id}/reporting-setup` | `{conversion_definition, attribution_window, confirmed}` | new linked manifest 201 | ML studio |
| POST `/ml/jobs` | `TrainingConfig {dataset_id, seed, as_of_date, label_lag_days}` | `ModelJob` 202 | ML studio |
| GET `/ml/jobs/{id}` | — | `ModelJob` (polled) | ML studio |
| POST `/ml/jobs/{id}/cancel` | — | `ModelJob` | ML studio |
| POST `/ml/models/{id}/evaluate` | — | `{model_id, test, notice}` | ML studio |
| POST `/ml/models/{id}/predict` | `Prediction` | `{predicted_revenue, uncertainty, notice, …}` | (API only) |
| GET `/ml/jobs/{id}/export` | — | evaluation JSON | ML studio |
| GET `/optimizer` | — | `{dataset_id, models, plans, suggested_start, policy}` | Budget studio, Story |
| POST `/optimizer/plans` | `PlanConfig` | `Plan` 201 | Budget studio |
| GET `/optimizer/plans/{id}` | — | `Plan` | Budget studio (restore, scenario review) |
| GET `/optimizer/plans/{id}/export` | `format=json\|csv` | file | Budget studio |
| GET `/ai/status` | — | `AIStatus` | Assistant |
| PUT `/ai/key` / DELETE `/ai/key` | `{api_key}` | `AIStatus` | Assistant |
| POST `/ai/test` | — | `AIStatus` (calls provider with no report data) | Assistant |
| GET `/ai/summary` | `kind∈{performance,model,budget}` | `{summary, summary_sha256, scope, local_reference}` | Assistant |
| POST `/ai/explain` | `{kind, summary_sha256, approved}` | `AIExplanation` | Assistant |
| GET `/commerce` | — | `{selected_order_batch_id, orders, costs, reconciliation, profit_plan, money_unit:"paisa", connected:false}` | Commerce |
| PUT `/commerce/selection` | `{order_batch_id}` | — | (API only) |
| POST `/commerce/imports/preview`, `/{token}/validate`, `/{token}/commit`; DELETE `/{token}` | CSV / `CommerceOptions` | stage / validation / meta | **API only in this release** |
| GET `/commerce/snapshots/{id}` | — | `CommerceReport` (money in **paisa**) | Commerce |
| GET `/commerce/snapshots/{id}/rows` | `table, status, page, page_size` | rows (paisa) | Commerce |
| DELETE `/commerce/snapshots/{id}` | — | `{deleted_snapshots}` | Commerce |
| GET `/commerce/campaigns/{ad_dataset_id}` | — | campaign candidates | (API only) |
| POST `/commerce/reconciliations` | `ReconcileConfig` | report + assessment | **API only in this release** |
| POST `/commerce/profit-plans` | `ProfitConfig` (budget PKR decimal) | `ProfitPlan` (PKR) | Commerce |
| GET `/commerce/snapshots/{id}/export` | `format, table` | file | Commerce |
| GET `/commerce/examples/{name}` | — | fictional CSV | (API only) |
| POST `/commerce/demo` | `variant=pilot\|history` | ids + notice | Commerce |

## Adapter notes (frontend/lib/api.ts)
- Types mirror the Pydantic/dict shapes above; no field renaming was needed, so no backend change was required for presentation.
- Unit conversion lives in the view: commerce report money ÷ 100 (paisa → PKR); profit plans are already PKR.
- Optimizer exact-total verification sums integer paisa client-side **only as a display check**; amounts themselves are never recomputed.
