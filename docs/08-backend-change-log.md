# 08 · Backend change log (protected area)

Two backend source changes were made (BC-1, BC-2), each with a failing test first, plus one test-only date fix (T-1). Every other file under `backend/src` is byte-identical to reference commit `23e788e`.

## BC-1 · Benchmark result publication fails on Windows

| Field | Detail |
|---|---|
| File | `backend/src/ads_optimizer/benchmarks/engine_runner.py`, `atomic_result()` |
| Severity | High on Windows (lab results silently incomplete); none on POSIX |
| Failing case | 10K benchmark, engines pandas+mapreduce, 2026-11-02. Job `completed`, but pandas result stayed `status: "running"` with 2 of 3 repeats; `pandas.tmp` left behind |
| Root cause | Engine writes `X.tmp` then `os.replace(X.tmp, X.json)`. The worker polls `X.json` every 0.15 s (`read_snapshot`). On Windows, replacing a file another process has open raises `PermissionError [WinError 5]`, crashing the engine's final write |
| Reproduction | `backend/tests/test_windows_atomic_result.py` holds the target open for 0.3 s; before the fix it fails with `PermissionError` |
| Patch | Retry `replace()` on `PermissionError` up to 100 × 50 ms (~5 s), then re-raise |
| Contract impact | None: same file format, same API responses, same timings measured (the retry happens after the timed repeats) |
| Validation | New test passes; `test_benchmarks.py` 27 pass (the 2 failures are the pre-existing Java/SIGKILL environment cases); real 10K/100K/1M runs → all repeats completed and parity-correct |
| Rollback | Revert the function to its original 3 lines; delete the test |

## BC-2 · Engine that exits mid-run keeps a non-terminal status (finding F-1)

Approved by the user on 2026-11-02 ("jo reh gya ha woh kro", following the F-1 approval request).

| Field | Detail |
|---|---|
| File | `backend/src/ads_optimizer/benchmarks/worker.py`, `measure_engine()` |
| Failing case | Engine publishes a `running` snapshot with 2 repeats, then exits with code 1 → result stayed `running` inside a `completed` job |
| Reproduction | `backend/tests/test_engine_exit_status.py` (fake engine process) failed with `'running' == 'failed'` before the patch |
| Patch | After the child exits, any status other than `completed`/`failed` becomes `failed` with "The engine exited before publishing all repeats…" |
| Contract impact | Status values already include `failed`; no new fields. Medians stay `null` (unchanged) |
| Validation | New test passes; `test_benchmarks.py` unchanged results (only the 2 Java/SIGKILL environment failures) |
| Rollback | Remove the `elif` branch; delete the test |

## T-1 · Stale date in an original test (test-only)
`backend/tests/test_schema_recognition.py::test_weekly_upload_actual_training_without_optional_counts` relied on `as_of_date` defaulting to `date.today()` while hard-coding `start_date=2026-11-02`, so it fails from 2026-11-02. The test now pins `as_of_date=2026-10-29` (its model's training as-of). Backend code unchanged; the backend's rejection was correct.
