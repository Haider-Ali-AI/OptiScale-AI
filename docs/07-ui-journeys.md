# 07 · Sitemap, journeys and data-to-component mapping

## Sitemap
| Route | Screen | Legacy route redirected here |
|---|---|---|
| `/` | Welcome & onboarding (3-path CTA) | — (old `/` overview now lives at `/overview`) |
| `/story` | University story mode | — |
| `/overview` | Executive overview | — |
| `/campaigns` | Campaign explorer | `/campaigns` (same) |
| `/data` | Data studio (`?mode=import` opens CSV upload) | `/data-studio` |
| `/budget` | Budget decision studio | `/budget-optimizer` |
| `/models` | ML validation studio | `/ml-studio` |
| `/lab` | Big Data lab | `/big-data-lab` |
| `/commerce` | Commerce & attribution | `/commerce` (same) |
| `/assistant` | AI insight assistant (optional) | `/ai-assistant` |
| `/methodology` | Methodology & help | `/help` |

Redirects are temporary (307) in `frontend/next.config.ts`.

## Core journeys
1. **First run**: Welcome → *Explore synthetic demo* (POST generate seed 42) → Overview. Or *Upload campaign CSV* → Data studio import wizard. Or *Understand the workflow* → Story.
2. **Analyse**: pick source (top bar) → Overview filters (server-side) → Campaign explorer (group / sort / page / export the same filters).
3. **Decide**: ML studio (readiness → train → poll → accept/reject → re-evaluate) → Budget studio (enter budget → method → limits → generate → exact check → export / restore / compare).
4. **Scale**: Big Data lab (scale + engines → start → poll → repeats + parity → scale chart → export).

## Per-screen acceptance (empty / loading / error / success)
| Screen | API | Empty | Loading | Error | Success |
|---|---|---|---|---|---|
| Overview | `GET analytics?group_by=platform` | NeedDataset; "no rows match filters" | skeleton; dimmed previous data during refetch | backend detail in Notice | KPIs, 4 charts, story, trust panel |
| Campaigns | `GET analytics` (+sort/page) | "no groups match" | skeleton | Notice | table + bars, paging |
| Data studio | workspace, preview, generate, imports/* | "no saved datasets" | Busy text per step | Notice per step | saved + selected confirmation |
| Budget | `GET optimizer`, `POST plans`, `GET plans/{id}` | "no plan yet" | Busy | Notice; client issue list mirrors backend validation | allocation, exact check, evidence, comparisons, exports |
| Models | `GET ml`, `POST readiness`, `POST jobs`, poll, evaluate | "no models yet" | Busy with stage | Notice | accept/reject + metrics |
| Lab | `GET lab`, `POST jobs`, poll, cancel, delete | "no runs" | progress bar | Notice; hosted → "Run locally" | per-engine results + parity + chart |
| Commerce | `GET commerce`, demo, snapshots | Empty | skeleton | Notice | 3 revenue origins, outcomes, costs, gated plan |
| Assistant | ai/status, summary, explain | key not configured → disabled with reason | Busy | sanitized provider error | explanation with provenance |

## Data → component mapping (selected)
- `Analytics.totals` → KPI strip, Funnel, Explain my KPI.
- `Analytics.platforms` → PlatformBars, Opportunity matrix, Performance story (ranking only; spend share = platform spend ÷ Σ spend).
- `Analytics.trend` + `trend_grain` → Timeline.
- `Manifest.coverage/warnings/…` → Data trust panel.
- `Plan.allocations/totals/comparisons/curves/forecast_reasons/baseline_assessment/limitations` → Budget studio.
- `ModelJob.result.test/validation/splits/acceptance/feature_importance/versions` → ML studio.
- `LabJob.results[].runs[]/dataset.reference/environment` → Lab.
