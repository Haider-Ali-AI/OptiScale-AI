"""Exact scaled-integer sums; weighted rates are derived only after reduction.

Money uses PKR paisa; fractional conversions use millionths. Missing totals propagate
when any row is missing, matching campaign analytics. Zero denominators yield null.
"""

import math

import numpy as np

from ads_optimizer.analytics.metrics import RATIOS
from ads_optimizer.benchmarks.contracts import UNIT_SCALES

SUM_FIELDS = ["rows", *UNIT_SCALES, *[f"known_{key}" for key in UNIT_SCALES]]
COLUMNS = ["platform", *UNIT_SCALES]


def empty():
    return {key: 0 for key in SUM_FIELDS}


def units(value, scale):
    return int(round(float(value) * scale)) if value is not None else 0


def reference_add(accumulator, frame):
    # Independent vector-mask reference, accumulated during bounded generation.
    for name in np.unique(frame.platform):
        subset = frame.loc[frame.platform == name]
        state = accumulator.setdefault(str(name), empty())
        state["rows"] += len(subset)
        for metric, scale in UNIT_SCALES.items():
            values = subset[metric].dropna().to_numpy()
            state[metric] += int(np.rint(values * scale).astype("int64").sum())
            state[f"known_{metric}"] += len(values)


def finalize(states):
    result = []
    for name, state in sorted(states.items()):
        totals = {
            key: state[key] / scale if state[f"known_{key}"] == state["rows"] else None
            for key, scale in UNIT_SCALES.items()
        }
        ratios = {}
        for key, (numerator, denominator, scale) in RATIOS.items():
            a, b = totals[numerator], totals[denominator]
            ratios[key] = a / b * scale if a is not None and b is not None and b > 0 else None
        result.append(
            {
                "name": name,
                "rows": state["rows"],
                **totals,
                **ratios,
                "coverage": {key: state[f"known_{key}"] / state["rows"] for key in UNIT_SCALES},
            }
        )
    return result


def parity(actual, expected):
    """Counts and unit sums exact; derived float rates use rtol=atol=1e-9."""
    if actual.keys() != expected.keys():
        return False
    if any(actual[name] != expected[name] for name in expected):
        return False
    observed, reference = finalize(actual), finalize(expected)
    return all(
        (a[key] is None and b[key] is None)
        or (
            a[key] is not None
            and b[key] is not None
            and math.isclose(a[key], b[key], rel_tol=1e-9, abs_tol=1e-9)
        )
        for a, b in zip(observed, reference, strict=True)
        for key in [*UNIT_SCALES, *RATIOS, "rows"]
    )
