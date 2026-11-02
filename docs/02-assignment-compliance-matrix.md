# 02 · Assignment compliance matrix

Source: `Project 2-Big_Data_Analytics (1).docx` (read in full, 2026-11-02). Status reflects evidence produced **on this machine**, not the reference repo's claims.

| Assignment requirement | Implementation (backend, unchanged) | SignalSpend screen | Test / run evidence | Status | Risk / note |
|---|---|---|---|---|---|
| Platforms: Facebook, Instagram, Google, TikTok, YouTube | `domain.PLATFORMS`, generator, importer | Data studio, Overview (fixed colour + shape per platform) | seed-42 10K source contains all five (API) | **Verified** | — |
| Fields: date, campaign, platform, impressions, clicks, spend, conversions, revenue, age, gender, city, device | `domain.FIELDS`; null-preserving import | Data studio mapping table, Trust panel coverage | coverage 100% for all fields on seed-42 | **Verified** | Imports may legitimately lack fields → shown as Not available |
| KPIs: CTR, CPC, CPA, conversion rate, ROAS, revenue, campaign performance | `analytics/metrics.py` (summed numerators ÷ denominators, None on 0/missing) | Overview KPI strip, Campaign explorer, Explain my KPI | backend tests pass; totals: CTR 1.584%, CPC Rs 19.14, CPA Rs 422.41, CVR 4.53%, ROAS 6.57× | **Verified** | Synthetic values, labelled |
| Simulate 10K / 100K / 1M / 10M records | `benchmarks/generator.py` (chunked Parquet) | Big Data lab | 10K, 100K, 1M generated & benchmarked 2026-11-02 | **Partially verified** | 10M not yet run on this machine (deliberate, long run; command documented) |
| Compare Pandas vs MapReduce vs Spark | `benchmarks/engines.py`, `engine_runner.py`, `worker.py` | Big Data lab (scale chart, repeats, parity) | Pandas + MapReduce: 3 scales × 3 repeats, all parity-correct | **Partially verified** | **Spark blocked**: no Java runtime (download failed: network). Windows publication race fixed — see 08 |
| Marketing Budget Recommendation Engine (allocate shares from simulated history) | `optimization/*` | Budget decision studio, Scenario review | Browser E2E: PKR 1,000,000 → XGBoost plan, sum exact to paisa; Google ≤20% cap respected | **Verified** | Advisory; synthetic outcomes; not causal |
| "Where should we spend the next Rs. 1 million?" | user enters 1000000 (no default) | Budget studio "Fill the assignment example" button | `docs/e2e-flows.json`, `docs/screenshots/flow-budget-1m-1440.png` | **Verified** | — |
| (Added value) Trained ML with baseline + acceptance | `ml/*` | ML validation studio | Accepted: holdout RMSE 7,195 vs baseline 10,416; re-evaluation identical | **Verified** | — |

Example allocation from the assignment brief (FB 25 / IG 30 / Google 35 / TikTok 10) is illustrative only; SignalSpend shows the engine's actual output with reasons rather than reproducing that example.
