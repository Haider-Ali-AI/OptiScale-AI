"""Budget feasibility is independent of forecast eligibility or observed spend scale."""

import math
import time
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np

from ads_optimizer.data.provenance import provenance_review
from ads_optimizer.domain import DomainError
from ads_optimizer.ml.baseline import assess_baseline
from ads_optimizer.ml.contracts import TrainingConfig
from ads_optimizer.ml.service import prepare, sha256
from ads_optimizer.ml.store import ModelStore
from ads_optimizer.optimization.allocate import allocate_cents, concave_minorant
from ads_optimizer.optimization.store import PlanStore


def evidence_plan(repo, config, reasons, assessment=None):
    from ads_optimizer.optimization.service import (
        POLICY,
        effective_limits,
        score_allocation,
        selected_source,
    )

    started = time.monotonic()
    with repo.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = selected_source(repo, config.dataset_id)
        limits = effective_limits(config)
        if config.start_date <= config.as_of_date:
            raise DomainError("Planning must start after the label as-of date.")
        frame = repo.read(source.id)
        period_days = 7 if source.date_granularity == "weekly" else 1
        lag = 0 if source.is_synthetic else config.label_lag_days
        cutoff = (config.as_of_date - timedelta(days=lag + period_days - 1)).isoformat()
        mature = frame[frame.date <= cutoff]
        if mature.empty:
            raise DomainError(
                "No complete observations are available by the label as-of date after the "
                "maturity lag. Choose a later as-of date or a report with earlier history. "
                "Later observations cannot set historical allocation priorities."
            )
        provenance = provenance_review(source)
        # When provenance is incomplete, revenue is not a defensible ranking input.
        financial = (
            not provenance
            and source.data_ready_for_revenue
            and source.coverage.get("spend") == 1
            and source.coverage.get("revenue") == 1
            and len(mature) > 0
        )
        use = mature
        histories = {}
        for p in limits:
            part = use[use.platform == p]
            if part.empty:
                raise DomainError(f"{p} has no observations in this dataset. Disable it.")
            spend = float(part.spend.fillna(0).sum())
            revenue = float(part.revenue.fillna(0).sum()) if financial else None
            rate = (revenue / spend if spend > 0 else 0) if financial else spend
            histories[p] = {"rows": len(part), "spend": spend, "revenue": revenue, "weight": rate}
        if not any(h["weight"] > 0 for h in histories.values()):
            for h in histories.values():
                h["weight"] = 1
        scale = max(h["weight"] for h in histories.values())
        curves = {}
        for p, limit in limits.items():
            points = np.unique(
                np.r_[
                    np.arange(
                        limit["lower_units"],
                        limit["upper_units"],
                        config.sample_step_cents,
                        dtype=np.int64,
                    ),
                    limit["upper_units"],
                ]
            )
            reference = max(
                1.0,
                histories[p]["spend"]
                / max(1, use.date.nunique())
                * config.horizon_days
                / period_days,
            )
            amounts = points / 100
            # Unitless priority utility; never exposed as revenue. Diminishing utility
            # encourages concentration for tiny budgets unless the user adds caps/floors.
            raw = histories[p]["weight"] / scale * amounts / (1 + amounts / reference)
            curves[p] = {
                **limit,
                "points": points,
                "raw": raw,
                "adjusted": concave_minorant(raw, points),
            }
        allocation = allocate_cents(curves, config.budget_cents)
        score = score_allocation(allocation, curves, config)
        for row in score["allocations"]:
            row.update(
                estimated_revenue=None,
                raw_estimated_revenue=None,
                next_step_revenue=None,
                reason="Historical priority with diminishing-utility assumptions; "
                "forecast evidence is insufficient. User limits are respected.",
            )
        score.update(estimated_revenue=None, raw_estimated_revenue=None, estimated_roas=None)
        report = {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": config.model_dump(mode="json"),
            "dataset": source.model_dump(mode="json"),
            "source_sha256": sha256(repo.root / "datasets" / source.id / "campaigns.parquet"),
            "is_synthetic": source.is_synthetic,
            "forecast_status": "unavailable",
            "forecast_reasons": list(dict.fromkeys(reasons + provenance)),
            "method_label": "Evidence-limited allocation · no revenue forecast · no ML",
            "model_id": None,
            "model_evidence": None,
            "baseline_assessment": assessment,
            "policy": POLICY,
            "currency": "PKR",
            "period_days": period_days,
            "curve_sample_step": config.sample_step_cents / 100,
            "objective": "Historical allocation priority under user constraints",
            "planning_end": (
                config.start_date + timedelta(days=config.horizon_days - 1)
            ).isoformat(),
            "training_period": {"start": str(use.date.min()), "end": str(use.date.max())},
            "training_controls": {
                "as_of_date": config.as_of_date.isoformat(),
                "label_lag_days": lag,
            },
            "coverage": {"input_rows": len(frame), "eligible_rows": len(mature)},
            "baseline": None,
            "history": histories,
            "user_limits": limits,
            "totals": {k: v for k, v in score.items() if k != "allocations"},
            "allocations": score["allocations"],
            "comparisons": [],
            "contexts": [],
            "curves": [],
            "uncertainty": "Revenue forecast unavailable",
            "notice": "Allocation only. Insufficient evidence for revenue or ROAS.",
            "limitations": [
                "Historical priority is not evidence of causal returns.",
                "Enter actual provider restrictions as user limits; none are assumed.",
                "Revenue is not used for ranking with unresolved provenance or incomplete labels.",
                "Recommendations only; no ad budgets are changed.",
            ],
            "prediction_rows": 0,
            "elapsed_seconds": time.monotonic() - started,
        }
        if (
            not math.isfinite(report["totals"]["budget"])
            or sum(allocation.values()) != config.budget_cents
        ):
            raise DomainError("Allocation did not satisfy the exact monetary total.")
        return PlanStore(repo.root).save(report)


def create_plan(repo, config):
    from ads_optimizer.optimization.service import (
        ForecastSupportError,
        _create_forecast_plan,
        effective_limits,
        selected_source,
    )

    source = selected_source(repo, config.dataset_id)
    effective_limits(config)  # Only genuine user constraints can make budgeting infeasible.
    if config.method == "evidence":
        return evidence_plan(repo, config, ["Allocation-only mode selected."])
    if config.method == "model":
        try:
            return _create_forecast_plan(repo, config)
        except ForecastSupportError as error:
            return evidence_plan(repo, config, [error.message])
    reasons = provenance_review(source)
    jobs = [
        j
        for j in ModelStore(repo.root).jobs()
        if j["status"] == "succeeded" and j["config"]["dataset_id"] == source.id
    ]
    if config.method == "auto" and not reasons:
        accepted = next((j for j in jobs if j["result"]["acceptance"]["eligible"]), None)
        if accepted:
            try:
                model_config = config.model_copy(
                    update={"method": "model", "model_id": accepted["id"]}
                )
                return _create_forecast_plan(repo, model_config, requested=config)
            except ForecastSupportError as error:
                reasons.append(error.message)
        else:
            reasons.append(
                "No accepted source-matched ML model. Evaluating the statistical baseline."
            )
    assessment = None
    if not provenance_review(source):
        try:
            _, _, parts, _ = prepare(
                repo,
                TrainingConfig(
                    dataset_id=source.id,
                    as_of_date=config.as_of_date,
                    label_lag_days=config.label_lag_days,
                ),
            )
            assessment = assess_baseline(parts)
            if assessment["eligible"]:
                baseline_config = config.model_copy(
                    update={"method": "historical", "model_id": None}
                )
                return _create_forecast_plan(
                    repo, baseline_config, requested=config, assessment=assessment
                )
            reasons += assessment["reasons"]
        except DomainError as error:
            if error.status != 422:
                raise
            reasons.append(error.message)
    return evidence_plan(repo, config, reasons, assessment)
