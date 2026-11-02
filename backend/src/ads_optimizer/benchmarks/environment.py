"""Read measured local resources and optional engine prerequisites without starting Spark."""

import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

import psutil


def version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def java_home():
    configured = os.environ.get("JAVA_HOME")
    if configured:
        return Path(configured)
    local = Path(__file__).resolve().parents[4] / ".runtime"
    for home in sorted(local.glob("*/Contents/Home"), reverse=True):
        if (home / "bin/java").is_file():
            return home
    return None


def java_info():
    home = java_home()
    executable = str(home / "bin/java") if home else shutil.which("java")
    if not executable:
        return None
    try:
        result = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=8)
        match = re.search(r'version "(\d+)[^\"]*"', result.stderr + result.stdout)
        if result.returncode == 0 and match:
            return {
                "major": int(match[1]),
                "description": (result.stderr + result.stdout).splitlines()[0][:180],
            }
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def environment(root: Path):
    try:
        memory = psutil.virtual_memory()
        ram_total, ram_available = memory.total, memory.available
    except (OSError, psutil.Error):
        ram_total = ram_available = None
    java = java_info()
    spark_version = version("pyspark")
    spark_ready = bool(spark_version and java and java["major"] in {17, 21, 25})
    return {
        "os": platform.platform(),
        "architecture": platform.machine(),
        "cpu": platform.processor() or platform.machine(),
        "logical_cpus": os.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "ram_total_bytes": ram_total,
        "ram_available_bytes": ram_available,
        "disk_free_bytes": shutil.disk_usage(root).free,
        "python": platform.python_version(),
        "packages": {
            name: version(name) for name in ["pandas", "numpy", "pyarrow", "pyspark", "psutil"]
        },
        "java": java,
        "input_format": "partitioned Parquet / Snappy",
        "engines": [
            {
                "id": "pandas",
                "label": "Pandas",
                "available": True,
                "reason": "In-memory groupby when safe; explicitly chunked for larger inputs.",
            },
            {
                "id": "mapreduce",
                "label": "Local MapReduce",
                "available": True,
                "reason": "Python process mappers, local shuffle/group, and a sum/count reducer.",
            },
            {
                "id": "spark",
                "label": "Apache Spark · local",
                "available": spark_ready,
                "reason": "Local PySpark DataFrame aggregation; no distributed cluster."
                if spark_ready
                else "Install the Spark extra and Java 17/21/25, then restart the service.",
            },
        ],
        "limits": {
            "max_rows": 10_000_000,
            "max_workers": 4,
            "max_memory_mib": 4096,
            "engine_timeout_seconds": 600,
            "job_timeout_seconds": 1800,
            "concurrent_jobs": 1,
            "disk_reserve_bytes": 1024**3,
        },
    }
