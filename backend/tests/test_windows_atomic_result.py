"""Regression: engine result publication must survive a concurrent reader on Windows.

On Windows, os.replace() onto a file that another process/handle has open raises
PermissionError (WinError 5). The benchmark worker polls the engine's result file
every 0.15 s, so the engine's final atomic write could crash and leave a stale
"running" snapshot in a completed job (observed 2026-11-02, 10K pandas run).
"""

import json
import threading
import time

from ads_optimizer.benchmarks.engine_runner import atomic_result


def test_atomic_result_retries_while_target_is_briefly_open(tmp_path):
    target = tmp_path / "pandas.json"
    target.write_text(json.dumps({"status": "running", "runs": [1, 2]}))
    handle = target.open("r")  # simulates the worker's read_snapshot() poll
    release = threading.Timer(0.3, handle.close)
    release.start()
    try:
        started = time.monotonic()
        atomic_result(target, {"status": "completed", "runs": [1, 2, 3]})
    finally:
        release.join()
        handle.close()
    assert json.loads(target.read_text()) == {"status": "completed", "runs": [1, 2, 3]}
    assert not target.with_suffix(".tmp").exists()
    assert time.monotonic() - started < 5
