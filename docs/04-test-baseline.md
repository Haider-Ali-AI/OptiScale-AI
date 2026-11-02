# 04 · Test baseline (before any change)

Environment: Windows 11 Home 10.0.26300 · Python 3.12.15 (`.venv`, `requirements.lock.txt`) · disposable `ADS_DATA_DIR` in the session scratchpad · no Java.

## Backend — unchanged reference source

Command: `python -m pytest -q -p no:cacheprovider` (from the project root; `pyproject.toml` sets `pythonpath`).

Result: **193 passed, 11 failed, 1 skipped** (88.5 s).

| Failing test | Cause | Class |
|---|---|---|
| `test_ai::test_private_key_lifecycle_and_truthful_status` | asserts POSIX file mode 0o600 (Windows reports 0o666) | Windows environment |
| `test_commerce::test_shopify_order_grain_privacy_and_repeated_totals` | same 0o600 mode assertion | Windows environment |
| `test_benchmarks::test_spark_real_local_parity_and_repeats` | `JAVA_GATEWAY_EXITED`: no Java runtime | Environment (Spark) |
| `test_benchmarks::test_cleanup_kills_orphan_group_after_runner_exits` | test uses `signal.SIGKILL` (POSIX only) | Windows environment |
| `test_serverless::*` (5 tests) | SQLite file still open during `TemporaryDirectory` cleanup (WinError 32); symlink privilege (WinError 1314) | Windows environment; hosted mode targets Linux |
| `test_schema_recognition::test_weekly_upload_actual_training_without_optional_counts` | hardcodes plan `start_date=2026-11-02` while `as_of_date` defaults to `date.today()` (= 2026-11-02); backend correctly rejects | **Stale test date** (passes before 2026-11-02) |

No failure indicates a defect in KPI maths, ML acceptance, optimizer totals, import validation or security logic.

Lint: `ruff check backend scripts` → **All checks passed**.

## Frontend — reference
Not executed: `npm ci` on the cloned third-party repository was blocked by the session's permission policy (installing/running external package scripts). The reference UI is being replaced, so its build is not a dependency of the new app.

## Runtime smoke (unchanged backend, this machine)
- `/health` OK; seed-42 10K generation; analytics totals; XGBoost training (accepted); commerce pilot demo; Pandas/MapReduce 10K benchmark → **defect discovered** (engine result publication race on Windows; see 08-backend-change-log.md).
