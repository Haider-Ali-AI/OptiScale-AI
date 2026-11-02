"""Independent temporal and exact-money checks for the pre-connector audit."""

import itertools
from datetime import date

import numpy as np
import pytest
from ads_optimizer.data.synthetic_generator import generate_frame
from ads_optimizer.domain import DomainError, GenerateConfig
from ads_optimizer.optimization.allocate import allocate_cents
from ads_optimizer.optimization.contracts import PlanConfig, PlatformLimit
from ads_optimizer.optimization.service import create_plan
from test_ml import save


def metadata():
    return {
        "name": "Simulated temporal audit fixture",
        "source": "synthetic_generator",
        "is_synthetic": True,
        "revenue_source": "synthetic",
        "data_ready_for_revenue": True,
        "warnings": [],
        "conversion_definition": "purchases",
        "attribution_window": "7-day click",
    }


@pytest.mark.parametrize(
    ("weekly", "as_of", "lag"),
    [
        (False, date(2025, 12, 31), 0),
        (False, date(2026, 1, 2), 7),
        (True, date(2026, 1, 3), 0),
    ],
)
def test_allocation_never_reads_later_or_incomplete_observations(
    isolated_repository, weekly, as_of, lag
):
    repo = isolated_repository
    frame, _ = generate_frame(GenerateConfig(rows=1000))
    # Simulated fixture exercises advertiser maturity behavior only in a test repo.
    if weekly:
        frame["date"] = "2026-01-01"
    source = repo.save(
        frame,
        {
            **metadata(),
            "is_synthetic": False,
            "date_granularity": "weekly" if weekly else "daily",
        },
    )
    config = PlanConfig(
        dataset_id=source.id,
        method="evidence",
        budget=500,
        as_of_date=as_of,
        label_lag_days=lag,
        start_date=date(2026, 2, 1),
    )
    with pytest.raises(DomainError, match="No complete observations"):
        create_plan(repo, config)


def test_allocation_only_priorities_ignore_records_after_as_of(isolated_repository):
    repo = isolated_repository
    source, frame = save(repo, rows=1000)
    cutoff = date(2026, 2, 1)
    early = frame[frame.date <= cutoff.isoformat()].copy()
    details = metadata()
    first = repo.save(early, details)

    def plan(source):
        return create_plan(
            repo,
            PlanConfig(
                dataset_id=source.id,
                method="evidence",
                budget=5432.19,
                as_of_date=cutoff,
                start_date=date(2026, 2, 2),
                platforms=[PlatformLimit(platform=p) for p in sorted(early.platform.unique())],
            ),
        )

    original = plan(first)
    frame.loc[frame.date > cutoff.isoformat(), "revenue"] *= 1_000_000
    later = repo.save(frame, details)
    changed = plan(later)
    assert original["allocations"] == changed["allocations"]
    assert original["totals"] == changed["totals"]
    assert original["history"] == changed["history"]


def test_exact_paisa_allocator_matches_independent_enumeration():
    """Audit the actual segment allocator, not just the older uniform-grid helper."""
    rng = np.random.default_rng(20261101)
    for _ in range(40):
        curves = {}
        for platform in ["Facebook", "Google", "TikTok"]:
            lower = int(rng.integers(0, 3))
            widths = rng.integers(1, 4, size=3)
            points = np.r_[lower, lower + np.cumsum(widths)]
            slopes = np.sort(rng.uniform(0.1, 10, size=3))[::-1]
            values = np.r_[0, np.cumsum(widths * slopes)]
            curves[platform] = {"points": points, "adjusted": values}
        floor = sum(int(c["points"][0]) for c in curves.values())
        cap = sum(int(c["points"][-1]) for c in curves.values())
        budget = int(rng.integers(floor, cap + 1))
        allocation = allocate_cents(curves, budget)

        def objective(amounts):
            return sum(
                float(np.interp(n, c["points"], c["adjusted"]))
                for n, c in zip(amounts, curves.values(), strict=True)
            )

        feasible = (
            choice
            for choice in itertools.product(
                *(range(int(c["points"][0]), int(c["points"][-1]) + 1) for c in curves.values())
            )
            if sum(choice) == budget
        )
        best = max(map(objective, feasible))
        assert sum(allocation.values()) == budget
        assert objective(allocation.values()) == pytest.approx(best)


def test_exact_ties_have_documented_name_order_independent_of_input_order():
    curve = {"points": np.array([0, 10]), "adjusted": np.array([0.0, 10.0])}
    forward = allocate_cents({"Facebook": curve, "Google": curve}, 10)
    reversed_input = allocate_cents({"Google": curve, "Facebook": curve}, 10)
    assert forward == reversed_input == {"Facebook": 10, "Google": 0}
