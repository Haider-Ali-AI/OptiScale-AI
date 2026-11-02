# Test report: 2026-11-02 (Windows 11, Python 3.12.15, Node 24.14.1, Edge headless)

| Check | Command | Result |
|---|---|---|
| Backend suite (after BC-1) | `python -m pytest -q -p no:cacheprovider` | **194 passed, 11 failed, 1 skipped**. The 11 are identical to the pre-change baseline (Windows/POSIX/Java/stale-date; see 04-test-baseline.md). +1 new regression test passes. No regressions |
| Backend lint | `ruff check backend scripts` | Passed |
| Frontend types + lint | `npm run check` (tsc + eslint) | Passed (0 errors, 0 warnings) |
| Production build | `npm run build` | Passed: 11 static routes + proxy |
| Hosted auth guard (`next start`, test password) | curl | no auth 401 · wrong 401 · right 200 · `/api/v1/workspace` no auth 401 · nosniff / DENY / same-origin headers present |
| Responsive & console QA | `node scripts/qa-screens.mjs` | 11 routes × 7 widths (320–1440), dark: **all 200, 0 console errors, 0 px horizontal overflow**. Light 320/768/1440: clean. Results `docs/qa-screens-*.json`, screenshots `docs/screenshots/` |
| Functional journeys | `node scripts/e2e-flows.mjs` | **10/10 pass** (`docs/e2e-flows.json`): PKR 1,000,000 exact to paisa (UI check + independent sum), method disclosed, stale estimates hidden after edits, Google ≤20% cap, constrained plan exact, model re-evaluation identical, server-side ROAS sort, legacy redirect, no page errors |
| Big Data lab (real runs, after BC-1) | Lab API, 3 repeats each | 10K · 100K · 1M with Pandas + MapReduce: all completed, all repeats parity-correct (`docs/evidence/run-*.json/csv`) |
| Spark | — | **Blocked**: no Java runtime (JDK download stalled; network unavailable) |
| 10M rows | — | **Not run** (deliberate long run pending) |
| NVIDIA live call | — | **Not run** (no key; optional) |

## Measured timings (median of 3 repeats, this laptop)
| Rows | Pandas | Local MapReduce (2 mappers) | Input generation |
|---|---|---|---|
| 10,000 | 0.031 s | 0.047 s | reused |
| 100,000 | 0.052 s | 0.216 s | 0.82 s |
| 1,000,000 | 0.384 s | 2.07 s | 7.65 s |

Single-machine measurements; MapReduce pays process/shuffle overhead that only pays off across machines.

## Issues found during QA and fixed
1. BC-1 backend Windows publication race (test-first fix).
2. Mobile overflow from implicit grid tracks, fieldset min-content, nowrap buttons and badges (CSS).
3. Desktop showed mobile menu buttons (selector specificity).
4. KPI values broke mid-number.
5. Response-curve chart drew fragments (switched to joined scatter series).
6. Scatter points were colour-only (added per-platform shapes).
7. Budget inputs could be edited during an in-flight request and get overwritten (inputs disabled while computing).
8. Ambiguous "vs recommended" column header.
