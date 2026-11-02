"""Exact PKR grid allocation over fixed active platforms and supported floors."""

import heapq

import numpy as np
from scipy.optimize import linprog

from ads_optimizer.domain import DomainError


def concave_minorant(raw, points=None):
    """Maximize the sum of a nonnegative, monotone concave curve below raw values.

    This is a planning assumption, not a new fit or an uncertainty interval.
    Floors fix the active-platform domain; concavity is only claimed on that grid.
    """
    raw = np.asarray(raw, dtype=float)
    if not len(raw) or not np.isfinite(raw).all() or (raw < 0).any():
        raise DomainError("Response values must be finite and nonnegative.")
    if len(raw) == 1:
        return raw.copy()
    n = len(raw)
    distances = np.diff(points) if points is not None else np.ones(n - 1)
    distances = distances / distances.max()
    constraints = []
    for i in range(n - 1):
        row = np.zeros(n)
        row[i], row[i + 1] = 1, -1
        constraints.append(row)
    for i in range(n - 2):
        row = np.zeros(n)
        left, right = distances[i], distances[i + 1]
        row[i : i + 3] = [right, -(left + right), left]
        constraints.append(row)
    # Scale the numerical problem; native prediction values can be large in PKR.
    scale = max(float(raw.max()), 1.0)
    fit = linprog(
        -np.ones(n),
        A_ub=np.array(constraints),
        b_ub=np.zeros(len(constraints)),
        bounds=[(0, float(v / scale)) for v in raw],
        method="highs",
    )
    if not fit.success:
        raise DomainError("Could not form supported response curves. Try a coarser step.", 409)
    values = np.maximum(0, fit.x * scale)
    # Remove solver roundoff from marginal ordering, retaining a conservative curve.
    slopes = np.minimum.accumulate(np.maximum(0, np.diff(values) / distances))
    adjusted = np.r_[values[0], values[0] + np.cumsum(slopes * distances)]
    positive = adjusted > 0
    if positive.any():
        adjusted *= min(1.0, float(np.min(raw[positive] / adjusted[positive])))
    return adjusted


def greedy(curves, units):
    allocation = {p: curve["lower_units"] for p, curve in curves.items()}
    remaining = units - sum(allocation.values())
    if remaining < 0 or units > sum(c["upper_units"] for c in curves.values()):
        raise DomainError("This budget is not feasible within the effective platform limits.")
    heap = []

    def push(platform):
        curve = curves[platform]
        index = allocation[platform] - curve["lower_units"]
        if allocation[platform] < curve["upper_units"]:
            gain = curve["adjusted"][index + 1] - curve["adjusted"][index]
            heapq.heappush(heap, (-gain, platform))

    for platform in curves:
        push(platform)
    for _ in range(remaining):
        if not heap:
            raise DomainError("No feasible platform remains for this budget increment.")
        _, platform = heapq.heappop(heap)
        allocation[platform] += 1
        push(platform)
    return allocation


def comparison_allocation(curves, units, weights):
    """Nearest feasible integer allocation to declared shares (squared distance)."""
    total = sum(weights.values())
    if total <= 0:
        raise DomainError("Historical spending is insufficient for a comparison.")
    target = {p: units * weights[p] / total for p in curves}
    allocation = {p: c["lower_units"] for p, c in curves.items()}
    for _ in range(units - sum(allocation.values())):
        eligible = [p for p, c in curves.items() if allocation[p] < c["upper_units"]]
        if not eligible:
            raise DomainError("Comparison constraints cannot cover this budget.")
        chosen = min(eligible, key=lambda p: (2 * (allocation[p] - target[p]) + 1, p))
        allocation[chosen] += 1
    return allocation


def allocate_cents(curves, budget):
    """Exact integer money on piecewise-linear concave curves, bounded by segments."""
    result = {p: int(c["points"][0]) for p, c in curves.items()}
    remaining = budget - sum(result.values())
    heap = []

    def push(p, index):
        c = curves[p]
        if index + 1 < len(c["points"]):
            capacity = int(c["points"][index + 1] - c["points"][index])
            gain = (c["adjusted"][index + 1] - c["adjusted"][index]) / capacity
            heapq.heappush(heap, (-gain, p, index, capacity))

    for p in curves:
        push(p, 0)
    while remaining > 0 and heap:
        _, p, index, capacity = heapq.heappop(heap)
        amount = min(remaining, capacity)
        result[p] += amount
        remaining -= amount
        if amount == capacity:
            push(p, index + 1)
    if remaining != 0:
        raise DomainError("The monetary limits cannot cover this budget.")
    return result


def comparison_cents(curves, budget, weights):
    """Project shares onto bounded monetary totals, then largest-remainder cents."""
    platforms = list(curves)
    targets = np.array([budget * weights[p] / sum(weights.values()) for p in platforms])
    lower = np.array([curves[p]["lower_units"] for p in platforms], dtype=np.int64)
    upper = np.array([curves[p]["upper_units"] for p in platforms], dtype=np.int64)
    lo, hi = -float(budget), float(budget)
    for _ in range(80):
        mid = (lo + hi) / 2
        if np.clip(targets + mid, lower, upper).sum() < budget:
            lo = mid
        else:
            hi = mid
    projected = np.clip(targets + (lo + hi) / 2, lower, upper)
    amounts = np.maximum(lower, np.minimum(upper, np.floor(projected).astype(np.int64)))
    residual = budget - int(amounts.sum())
    for i in sorted(
        range(len(platforms)), key=lambda i: (-(projected[i] - amounts[i]), platforms[i])
    ):
        if residual > 0 and amounts[i] < upper[i]:
            amounts[i] += 1
            residual -= 1
    if residual:
        raise DomainError("Comparison could not satisfy exact monetary limits.")
    return dict(zip(platforms, map(int, amounts), strict=True))
