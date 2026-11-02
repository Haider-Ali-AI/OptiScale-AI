# 08 · Backend change log (protected area)

Only one backend source change was made. Every other file under `backend/src` is byte-identical to reference commit `23e788e`.

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

## Open finding (not changed, needs approval)
**F-1 · Non-terminal engine status inside a finished job.** `worker.measure_engine` downgrades only `completed` snapshots that fail the gate. If an engine process dies after publishing an intermediate `running` snapshot, that status is stored inside a `completed` job. Median stays `null`, so no timing is fabricated, but the report is misleading.
Proposed patch: after the child exits, `if snapshot["status"] not in {"completed","failed"}: snapshot.update(status="failed", message="Engine exited before publishing all repeats.")`, plus a test with a runner that exits mid-way. Changes stored report semantics, so it awaits user approval. **Frontend mitigation already in place:** such results are displayed as "incomplete" with an explanation.
