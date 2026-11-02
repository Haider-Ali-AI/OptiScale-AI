# Test report: 2026-11-02 (Windows 11, Python 3.12.15, Node 24.14.1, Temurin JRE 17.0.20.1, Edge headless)

| Check | Command | Result |
|---|---|---|
| Backend suite (after BC-1, BC-2, T-1; with Java) | `python -m pytest -q -p no:cacheprovider` | **197 passed, 9 failed, 1 skipped**. All 9 are Windows/POSIX-specific: file mode 0o600 (2), `signal.SIGKILL` (1), SQLite temp-dir lock in serverless tests (5), symlink privilege (1). Spark parity test now **passes**. 2 new regression tests pass. No regressions vs baseline |
| Backend lint | `ruff check backend scripts` | Passed |
| Frontend types + lint | `npm run check` | Passed (0 errors, 0 warnings) |
| Production build | `npm run build` | Passed: 11 static routes + proxy |
| Hosted auth guard (`next start`, test password) | curl | no auth 401 · wrong 401 · right 200 · API without auth 401 · security headers present |
| Responsive & console QA | `node scripts/qa-screens.mjs` (+ light theme) | 11 routes × 7 widths dark, 11 × 4 light: **all 200, 0 console errors, 0 px horizontal overflow** |
| Core journeys | `node scripts/e2e-flows.mjs` | **10/10**: PKR 1,000,000 exact to paisa, method disclosed, stale estimates hidden, Google ≤20% cap, constrained plan exact, model re-evaluation identical, server ROAS sort, legacy redirect, no page errors |
| Commerce journeys | `node scripts/e2e-commerce.mjs` | **8/8**: order + cost CSV import and comparison via the UI reproduce the backend demo exactly (net sales Rs 6,400.00, matched Rs 5,150.00, outcomes 4/1/1/2, reference diff 0) |
| Big Data lab | Lab API, 3 repeats, all 3 engines per job | **4 scales × 3 engines: every repeat parity-correct** (`docs/evidence/all-engines-*`) |
| NVIDIA live call | — | Not run (no key; optional feature) |
| Hosted/serverless tests on Linux | — | Not run (no Linux environment; WSL has only docker-desktop) |

## Final run (after public demo + NVIDIA + story removal)
| Where | Result |
|---|---|
| Backend pytest (Java on) | 201 passed, 9 failed (Windows/POSIX-only, unchanged), 1 skipped |
| Ruff / tsc / ESLint / build | all passed |
| Local: QA 10 routes × 7 widths; E2E core; commerce; assistant | clean; 10/10; 8/8; 8/8 |
| Live (no login): QA 10 routes × 3 widths; E2E core; commerce; assistant | clean; 10/10; 8/8; 8/8 |
| Live security | deletes 403, key changes 403, cross-site writes 403 |

## Measured timings: median of 3 measured repeats (setup excluded)
Same job per scale, seed 42, 2 workers, this laptop (10 physical cores, ~4 GB RAM free during runs).

| Rows | Pandas | Local MapReduce | Local Spark | Spark setup (JVM) |
|---|---|---|---|---|
| 10,000 | 0.014 s | 0.038 s | 0.682 s | 11.0 s |
| 100,000 | 0.041 s | 0.213 s | 0.935 s | 10.8 s |
| 1,000,000 | 0.344 s | 2.128 s | 2.063 s | 14.2 s |
| 10,000,000 | 7.471 s (chunked) | 21.590 s | 9.740 s | 10.1 s |

Reading: Pandas wins on one machine at every scale. Spark's fixed overhead dominates small inputs, it overtakes MapReduce from about 1M rows, and at 10M it is ~2.2× faster than MapReduce. Pandas switches to bounded chunks at 10M to stay inside the memory allowance. These are single-machine results, not cluster claims. Separate 10M run earlier (Pandas + MapReduce only): Pandas 4.34 s, MapReduce 22.2 s, which shows run-to-run variance under memory pressure.

## Issues found and fixed
1. BC-1: Windows engine-result publication race (backend, test-first).
2. BC-2: engine exiting mid-run left a `running` status in a completed job (backend, test-first, user-approved).
3. T-1: stale hardcoded date in an original test.
4. Mobile overflow (grid tracks, fieldset min-content, nowrap buttons/badges).
5. Desktop showed mobile menu buttons.
6. KPI values broke mid-number.
7. Response-curve chart drew fragments.
8. Scatter points were colour-only (shapes added).
9. Budget inputs editable during an in-flight request (now disabled while computing).
10. Ambiguous "vs recommended" column header; truncated lab job-type label.
