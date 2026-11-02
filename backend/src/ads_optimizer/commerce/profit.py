"""Screened commerce contribution response; separate from ad-revenue ML models."""

import itertools
from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd

from ads_optimizer.commerce.contracts import ProfitConfig
from ads_optimizer.commerce.store import CommerceStore
from ads_optimizer.domain import DomainError
from ads_optimizer.ml.evaluate import metrics
from ads_optimizer.ml.features import chronological_split
from ads_optimizer.optimization.allocate import allocate_cents, comparison_cents
from ads_optimizer.optimization.contracts import PlanConfig
from ads_optimizer.optimization.service import effective_limits

POLICY = "commerce-contribution-v1"


def response(spend, coefficient, reference):
    return coefficient * 2 * np.asarray(spend) / (1 + np.asarray(spend) / reference)


def assess(report):
    reasons = list(report["profit"]["forecast_reasons"])
    if reasons:
        return {"eligible": False, "reasons": reasons, "policy": POLICY}
    rows = [row for row in report["observations"] if row["mature"]]
    if any(
        row["spend"] is None
        or row["contribution_before_ads"] is None
        or row["contribution_before_ads"] < 0
        for row in rows
    ):
        reasons.append(
            (
                "The nonnegative contribution-response pilot cannot fit missing or "
                "loss-making pre-ad observations."
            )
        )
    if reasons:
        return {"eligible": False, "reasons": reasons, "policy": POLICY}
    frame = pd.DataFrame(rows)
    if frame.empty:
        return {
            "eligible": False,
            "reasons": ["No mature commerce/ad observations are available."],
            "policy": POLICY,
        }
    frame["spend"] = frame.spend / 100
    frame["target"] = frame.contribution_before_ads / 100
    try:
        training, validation, test = chronological_split(frame)
    except DomainError as error:
        return {"eligible": False, "reasons": [error.message], "policy": POLICY}
    parameters, evaluation = {}, {}
    for platform, group in training.groupby("platform"):
        positive = group[group.spend > 0]
        if len(positive) < 20 or positive.spend.nunique() < 3:
            reasons.append(f"{platform} needs enough positive training spend and variation.")
            continue
        reference = float(positive.spend.median())
        shape = response(group.spend.to_numpy(), 1, reference)
        coefficient = max(0, float(np.dot(shape, group.target) / np.dot(shape, shape)))
        parameters[platform] = {
            "coefficient": coefficient,
            "reference_daily_spend": reference,
            "minimum_daily_spend": float(positive.spend.min()),
            "maximum_daily_spend": float(positive.spend.max()),
            "historical_spend": float(group.spend.sum()),
        }
    for name, part in [("validation", validation), ("holdout", test)]:
        local = {}
        for platform in sorted(frame.platform.unique()):
            group = part[part.platform == platform]
            if platform not in parameters or len(group) < 5:
                reasons.append(f"{platform} lacks {name} temporal support.")
                continue
            parameter = parameters[platform]
            predicted = response(
                group.spend.to_numpy(), parameter["coefficient"], parameter["reference_daily_spend"]
            )
            score = metrics(group.target, predicted)
            constant = metrics(
                group.target,
                np.full(len(group), float(training[training.platform == platform].target.mean())),
            )
            local[platform] = {"response": score, "train_mean": constant}
            if score["wape"] is None or score["wape"] > 1 or score["rmse"] >= constant["rmse"]:
                reasons.append(
                    f"{platform} {name} response must beat train-mean RMSE "
                    "and have WAPE at most one hundred percent."
                )
        evaluation[name] = local
    return {
        "eligible": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "policy": POLICY,
        "parameters": parameters,
        "evaluation": evaluation,
        "splits": {
            name: {"rows": len(part), "start": part.date.min(), "end": part.date.max()}
            for name, part in [("train", training), ("validation", validation), ("holdout", test)]
        },
        "target": (
            "Matched order-cohort contribution before ads; tax excluded; declared "
            "shipping/cost basis."
        ),
        "method": "Train-only fitted contribution response with assumed saturation; not XGBoost.",
        "limitations": (
            "Operational chronological screen, not calibrated uncertainty or causal"
            " merchant validation."
        ),
    }


def create(repo, config: ProfitConfig):
    store = CommerceStore(repo.root)
    meta, report = store.get(config.reconciliation_id, "reconciliation")
    # Current source existence matters; historical reports remain immutable.
    repo.get(meta["ad_dataset_id"])
    assessment = assess(report)
    if not assessment["eligible"]:
        raise DomainError("Profit forecast unavailable: " + " ".join(assessment["reasons"]))
    snapshot = date.fromisoformat(report["orders_manifest"]["definitions"]["snapshot_as_of"])
    last = date.fromisoformat(assessment["splits"]["holdout"]["end"])
    if config.start_date <= snapshot or (config.start_date - last).days + config.horizon_days > 90:
        raise DomainError(
            "Plan after the verified snapshot and within ninety days of mature history."
        )
    parameters = assessment["parameters"]
    if any(limit.platform not in parameters for limit in config.platforms):
        raise DomainError("Only enable platforms supported by this commerce history.")
    shared = PlanConfig(
        dataset_id=meta["ad_dataset_id"],
        budget=float(config.budget),
        start_date=config.start_date,
        platforms=config.platforms,
    )
    limits = effective_limits(shared)
    best = None
    platforms = sorted(limits)
    # Positive historical support is a forecast gate, never a forced spending budget.
    for length in range(1, len(platforms) + 1):
        for active in itertools.combinations(platforms, length):
            curves = {}
            for platform in platforms:
                limit, parameter = limits[platform], parameters[platform]
                if platform not in active:
                    if limit["lower_units"]:
                        break
                    lower = upper = 0
                else:
                    lower = max(
                        limit["lower_units"],
                        int(
                            Decimal(str(parameter["minimum_daily_spend"]))
                            * config.horizon_days
                            * 100
                        ),
                    )
                    upper = min(
                        limit["upper_units"],
                        int(
                            Decimal(str(parameter["maximum_daily_spend"]))
                            * config.horizon_days
                            * 100
                        ),
                    )
                    if lower > upper:
                        break
                points = np.unique(
                    np.linspace(lower, upper, min(201, upper - lower + 1), dtype=np.int64)
                )
                curves[platform] = {
                    "points": points,
                    "lower_units": lower,
                    "upper_units": upper,
                    "adjusted": response(
                        points / 100,
                        parameter["coefficient"],
                        parameter["reference_daily_spend"] * config.horizon_days,
                    ),
                }
            if len(curves) != len(platforms) or not sum(
                c["lower_units"] for c in curves.values()
            ) <= shared.budget_cents <= sum(c["upper_units"] for c in curves.values()):
                continue
            allocation = allocate_cents(curves, shared.budget_cents)
            value = sum(
                float(np.interp(allocation[p], curves[p]["points"], curves[p]["adjusted"]))
                for p in platforms
            )
            if best is None or value > best[0]:
                best = value, curves, allocation
    if best is None:
        raise DomainError(
            "This budget has no supported profit forecast within the selected limits. "
            + (
                "Change limits or use ordinary Budget Optimizer for allocation without "
                "a profit forecast."
            )
        )
    value, curves, allocation = best

    def scored(amounts):
        before_ads = sum(
            float(np.interp(amounts[p], curves[p]["points"], curves[p]["adjusted"]))
            for p in platforms
        )
        return {
            "budget": sum(amounts.values()) / 100,
            "estimated_contribution_before_ads": before_ads,
            "estimated_contribution_profit": before_ads - float(config.budget),
            "allocations": [
                {
                    "platform": p,
                    "budget": amounts[p] / 100,
                    "minimum": curves[p]["lower_units"] / 100,
                    "maximum": curves[p]["upper_units"] / 100,
                }
                for p in platforms
            ],
        }

    comparisons = []
    for label, weights in [
        (
            "Equal split under the same active-platform support",
            {p: int(curves[p]["upper_units"] > 0) for p in platforms},
        ),
        (
            "Historical spend under the same support",
            {p: parameters[p]["historical_spend"] for p in platforms},
        ),
    ]:
        comparisons.append(
            {"name": label, **scored(comparison_cents(curves, shared.budget_cents, weights))}
        )
    payload = {
        "config": config.model_dump(mode="json"),
        "assessment": assessment,
        "result": scored(allocation),
        "comparisons": comparisons,
        "notice": "Estimated advisory contribution profit from a screened historical response. "
        + (
            "Saturation and fixed cost mix are assumptions. Uncertainty is "
            "unquantified; no causal or profit guarantee."
        ),
        "curve_points": {
            p: [
                {"budget": int(point) / 100, "estimated_contribution_before_ads": float(value)}
                for point, value in zip(curves[p]["points"], curves[p]["adjusted"], strict=True)
            ]
            for p in platforms
        },
    }
    manifest = store.save(
        "profit_plan",
        {
            "name": "Advisory contribution plan",
            "store_id": meta["store_id"],
            "is_synthetic": meta["is_synthetic"],
            "dependencies": [meta["id"]],
        },
        payload,
    )
    return {"manifest": manifest, **payload}
