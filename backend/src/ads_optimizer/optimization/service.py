"""Repeatable campaign-day planning; measured model output, explicit shape assumptions."""

import csv
import io
import itertools
import json
import math
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ads_optimizer.analytics.metrics import safe_csv_cell
from ads_optimizer.domain import DomainError
from ads_optimizer.ml.contracts import TrainingConfig
from ads_optimizer.ml.evaluate import fit_baseline
from ads_optimizer.ml.features import CATEGORICAL
from ads_optimizer.ml.infer import load_model, predict_frame
from ads_optimizer.ml.service import prepare, sha256
from ads_optimizer.ml.store import ModelStore
from ads_optimizer.optimization.allocate import (
    allocate_cents,
    comparison_cents,
    concave_minorant,
)
from ads_optimizer.optimization.store import PlanStore

POLICY = "planning-evidence-v3"
MAX_PREDICTION_ROWS = 200_000
MAX_CONTEXT_ROWS = 100
LIMITATIONS = [
    "Recommendations only; no ad budgets are changed.",
    "Uncertainty is not quantified. Forecast differences are estimates, not observed gains.",
    "Platform attribution can overlap. Summed attributed revenue is not unique store sales.",
    "Observational predictions do not establish causal returns from reallocating spend.",
    "The representative mix repeats each reporting period; no campaign selection, "
    "audience interaction, cross-platform substitution or new-campaign effect is modeled.",
    "Supported spend uses platform-wide training bounds; context-specific support and future "
    "seasonality are not independently validated. Review campaign execution separately.",
    "Monotonicity and diminishing returns are planning assumptions. Adjusted curves are "
    "conservative relative to sampled raw outputs, not statistical lower confidence bounds.",
]


def selected_source(repo, dataset_id):
    source = repo.get(dataset_id)
    selected = repo.selected()
    if not selected or selected.id != source.id:
        raise DomainError("Select this plan's source dataset before continuing.", 409)
    return source


def optimizer_state(repo):
    source = repo.selected()
    jobs = ModelStore(repo.root).jobs()
    models = [
        {
            "id": job["id"],
            "algorithm": job["result"]["algorithm"],
            "eligible": job["result"]["acceptance"]["eligible"],
            "reasons": job["result"]["acceptance"]["reasons"],
            "as_of_date": job["config"]["as_of_date"],
            "test_end": job["result"]["splits"]["test"]["end"],
        }
        for job in jobs
        if source and job["config"]["dataset_id"] == source.id and job["status"] == "succeeded"
    ]
    start = max(
        [date.today().isoformat(), source.date_end if source else "0001-01-01"]
        + [max(m["as_of_date"], m["test_end"]) for m in models]
    )
    suggested = date.fromisoformat(start) + timedelta(days=1)
    if source and source.date_granularity == "weekly":
        weekday = date.fromisoformat(source.date_start).weekday()
        suggested += timedelta(days=(weekday - suggested.weekday()) % 7)
    return {
        "dataset_id": source.id if source else None,
        "models": models,
        "plans": PlanStore(repo.root).list(source.id) if source else [],
        "suggested_start": suggested.isoformat(),
        "policy": POLICY,
    }


def representative_contexts(training, platforms, horizon, *, historical=False):
    """Select a real training date closest to each platform's median period spend.

    All rows of that day are retained, with historical within-day spend weights.
    Never use holdout outcomes or simulator truth for this context policy.
    """
    contexts = {}
    for platform in sorted(platforms):
        part = training[(training.platform == platform) & (training.spend > 0)]
        if (
            part.empty
            or part.spend.min() <= 0
            or part.spend.nunique() < (3 if historical else 10)
            or (historical and (len(part) < 5 or part.date.nunique() < 4))
        ):
            raise ForecastSupportError(
                f"{platform} needs positive spends, sufficient periods and spend variation. "
                "Disable this platform or provide a suitable campaign report."
            )
        totals = part.groupby("date", sort=True).spend.sum()
        chosen = (totals - totals.median()).abs().sort_values(kind="stable").index[0]
        # Stable sort makes repeated results independent of row ordering.
        columns = [c for c in ["campaign", "campaign_id", "account_id", *CATEGORICAL] if c in part]
        rows = part[part.date == chosen].sort_values(columns, kind="stable").copy()
        if len(rows) > MAX_CONTEXT_ROWS:
            raise DomainError(
                f"{platform}'s representative day exceeds 100 campaign/segment rows. "
                "Use a coarser, non-overlapping campaign report."
            )
        weights = rows.spend.to_numpy(dtype=float) / float(rows.spend.sum())
        low = float(part.spend.min())
        high = float(part.spend.max())
        contexts[platform] = {
            "rows": rows,
            "weights": weights,
            "date": str(chosen),
            "reference_budget": float(rows.spend.sum()) * horizon,
            "supported_min": low * horizon / float(weights.min()),
            "supported_max": high * horizon / float(weights.max()),
            "row_spend_min": low,
            "row_spend_max": high,
            "historical_spend": float(part.spend.sum()),
        }
    return contexts


class ForecastSupportError(DomainError):
    """Forecast support is limited; budget allocation may still be feasible."""


def effective_limits(config, contexts=None):
    limits = {}
    for p in config.platforms:
        lower = max(
            (config.budget_cents * p.min_percent + 99) // 100, int(round(p.min_amount * 100))
        )
        upper = min(
            config.budget_cents * p.max_percent // 100,
            int(round(p.max_amount * 100)) if p.max_amount is not None else config.budget_cents,
        )
        if lower > upper:
            raise DomainError(
                f"{p.platform}: user minimum PKR {lower / 100:,.2f} exceeds "
                f"maximum PKR {upper / 100:,.2f}."
            )
        limits[p.platform] = {
            "lower_units": lower,
            "upper_units": upper,
            "requested_min_percent": p.min_percent,
            "requested_max_percent": p.max_percent,
        }
    if (
        not sum(c["lower_units"] for c in limits.values())
        <= config.budget_cents
        <= sum(c["upper_units"] for c in limits.values())
    ):
        raise DomainError(
            "User platform minimums/maximums cannot cover the requested budget. "
            "Adjust those explicit limits."
        )
    return limits


def forecast_limits(config, contexts):
    limits = {}
    monetary = effective_limits(config)
    for request in config.platforms:
        context = contexts[request.platform]
        # Work in paisa: percentage floors round up, caps round down.
        lower = max(
            monetary[request.platform]["lower_units"],
            math.ceil(context["supported_min"] * 100 - 1e-7),
        )
        upper = min(
            monetary[request.platform]["upper_units"],
            math.floor(context["supported_max"] * 100 + 1e-7),
        )
        if lower > upper:
            if monetary[request.platform]["lower_units"] > 0:
                raise ForecastSupportError(
                    f"{request.platform} forecast support does not cover the user floor."
                )
            lower, upper = 0, 0
        limits[request.platform] = {
            "lower_units": lower,
            "upper_units": upper,
            "requested_min_percent": request.min_percent,
            "requested_max_percent": request.max_percent,
        }
    return limits


def model_curve(context, budgets, config, model, encoder, check, period_days=1):
    rows = context["rows"][CATEGORICAL].copy()
    dates = [
        config.start_date + timedelta(days=i) for i in range(0, config.horizon_days, period_days)
    ]
    frames = []
    for budget in budgets:
        for day in dates:
            frame = rows.copy()
            frame["date"] = day.isoformat()
            frame["spend"] = context["weights"] * budget / (config.horizon_days // period_days)
            if (
                frame.spend.min() < context["row_spend_min"] - 1e-6
                or frame.spend.max() > context["row_spend_max"] + 1e-6
            ):
                raise DomainError("A candidate campaign-period spend exceeded training support.")
            frames.append(frame)
    frame = pd.concat(frames, ignore_index=True)
    check()
    prediction = predict_frame(model, encoder, frame)
    check()
    return prediction.reshape(len(budgets), -1).sum(axis=1)


def score_allocation(allocation, curves, config):
    rows = []
    total_units = config.budget_cents
    # Largest remainders make displayed hundredths of a percent total exactly 100.00.
    basis_points = {p: n * 10_000 // total_units for p, n in allocation.items()}
    remainders = sorted(allocation, key=lambda p: (-(allocation[p] * 10_000 % total_units), p))
    for platform in remainders[: 10_000 - sum(basis_points.values())]:
        basis_points[platform] += 1
    for platform, units in allocation.items():
        curve = curves[platform]
        points = curve["points"]
        adjusted = float(np.interp(units, points, curve["adjusted"]))
        raw = float(np.interp(units, points, curve["raw"]))
        next_gain = (
            float(
                np.interp(
                    min(units + config.sample_step_cents, points[-1]), points, curve["adjusted"]
                )
            )
            - adjusted
            if units < points[-1]
            else None
        )
        rows.append(
            {
                "platform": platform,
                "budget": units / 100,
                "share_percent": basis_points[platform] / 100,
                "estimated_revenue": adjusted,
                "raw_estimated_revenue": raw,
                "next_step_revenue": next_gain,
                "effective_min": curve["lower_units"] / 100,
                "effective_max": curve["upper_units"] / 100,
                "requested_min_percent": curve["requested_min_percent"],
                "requested_max_percent": curve["requested_max_percent"],
                "reason": "At the effective upper limit; further steps are unavailable."
                if units == curve["upper_units"]
                else "At the effective minimum; other channels received the available steps."
                if units == curve["lower_units"]
                else "Received additional steps under the adjusted marginal-revenue rule.",
            }
        )
    total = sum(row["estimated_revenue"] for row in rows)
    return {
        "allocations": sorted(rows, key=lambda row: (-row["budget"], row["platform"])),
        "budget": sum(allocation.values()) / 100,
        "estimated_revenue": total,
        "raw_estimated_revenue": sum(row["raw_estimated_revenue"] for row in rows),
        "estimated_roas": total / config.budget,
    }


def _create_forecast_plan(repo, config, *, requested=None, assessment=None):
    started = time.monotonic()

    def check():
        if time.monotonic() - started > 20:
            raise DomainError(
                "Planning exceeded 20 seconds. Use a coarser step or shorter horizon."
            )

    # Source selection/deletion and report publication share the source catalog lock.
    # Short bounded planning requests serialize local writes rather than publish stale results.
    with repo.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        source = selected_source(repo, config.dataset_id)
        path = repo.root / "datasets" / source.id / "campaigns.parquet"
        source_hash = sha256(path)
        store = ModelStore(repo.root)
        model, encoder, job = None, None, None
        if config.method == "model":
            job = store.published(config.model_id)
            if job["config"]["dataset_id"] != source.id:
                raise DomainError("Choose a model trained on the selected dataset.", 409)
            if not job["result"]["acceptance"]["eligible"]:
                raise DomainError("This model failed acceptance checks. Choose another model.", 409)
            if job.get("input_sha256") != source_hash:
                raise DomainError("Model input checksum differs from this source. Retrain.", 409)
            training_config = TrainingConfig.model_validate(job["config"])
            boundary = max(job["config"]["as_of_date"], job["result"]["splits"]["test"]["end"])
        else:
            training_config = TrainingConfig(
                dataset_id=source.id,
                as_of_date=config.as_of_date,
                label_lag_days=config.label_lag_days,
            )
            boundary = config.as_of_date.isoformat()
        if config.start_date.isoformat() <= boundary:
            raise DomainError("Planning must start after the model/report label as-of date.")
        if (config.start_date - date.fromisoformat(boundary)).days + config.horizon_days > 90:
            raise ForecastSupportError(
                "Forecast horizon exceeds 90 days from the label as-of date."
            )
        if config.start_date.year >= 9999:
            raise DomainError("Choose a supported planning year before 9999.")
        period_days = 7 if source.date_granularity == "weekly" else 1
        if config.horizon_days % period_days:
            raise ForecastSupportError(
                "Weekly reports require a horizon of 7, 14, 21 or 28 days; "
                "weekly totals cannot be divided into daily predictions."
            )
        if (
            period_days == 7
            and config.start_date.weekday() != date.fromisoformat(source.date_start).weekday()
        ):
            raise ForecastSupportError(
                "Weekly forecast starts must align with the report week-start day."
            )
        _, _, parts, coverage = prepare(
            repo, training_config, historical=job is None and assessment is None
        )
        training = parts[0]
        if job and (
            training.date.min() != job["result"]["splits"]["train"]["start"]
            or training.date.max() != job["result"]["splits"]["train"]["end"]
            or len(training) != job["result"]["splits"]["train"]["rows"]
        ):
            raise DomainError("The saved training split no longer matches. Retrain.", 409)
        contexts = representative_contexts(
            training,
            [p.platform for p in config.platforms],
            config.horizon_days // period_days,
            historical=job is None,
        )
        curves = forecast_limits(config, contexts)
        for curve in curves.values():
            curve["points"] = np.unique(
                np.r_[
                    np.arange(
                        curve["lower_units"],
                        curve["upper_units"],
                        config.sample_step_cents,
                        dtype=np.int64,
                    ),
                    curve["upper_units"],
                ]
            )
        work_rows = sum(
            int(np.count_nonzero(c["points"]))
            * len(contexts[p]["rows"])
            * (config.horizon_days // period_days)
            for p, c in curves.items()
        )
        if work_rows > MAX_PREDICTION_ROWS:
            raise DomainError(
                "This grid exceeds 200,000 campaign-day predictions. "
                "Increase the step or shorten the horizon."
            )
        if job:
            _, model, encoder = load_model(store, config.model_id)
        baseline = fit_baseline(training)
        for platform, curve in curves.items():
            check()
            context = contexts[platform]
            budgets = curve["points"] / 100
            if not np.any(budgets):
                raw = np.zeros(len(budgets))
            elif job:
                raw = model_curve(context, budgets, config, model, encoder, check, period_days)
            else:
                # Calibrates to the smoothed training ROAS at the representative budget.
                # The saturation shape is assumed, never described as learned causal response.
                rate = baseline["platform_rates"][platform]
                raw = 2 * rate * budgets / (1 + budgets / context["reference_budget"])
            curve["raw"] = raw
            curve["adjusted"] = concave_minorant(raw, curve["points"])
        units = config.budget_cents
        feasible = []
        names = list(curves)
        monetary = effective_limits(config)
        for bits in itertools.product([False, True], repeat=len(names)):
            variant = {}
            for p, active in zip(names, bits, strict=True):
                if not active:
                    if monetary[p]["lower_units"] > 0:
                        break
                    variant[p] = {
                        **curves[p],
                        "lower_units": 0,
                        "upper_units": 0,
                        "points": np.array([0]),
                        "raw": np.array([0.0]),
                        "adjusted": np.array([0.0]),
                    }
                else:
                    variant[p] = curves[p]
            else:
                if (
                    sum(c["lower_units"] for c in variant.values())
                    <= units
                    <= sum(c["upper_units"] for c in variant.values())
                ):
                    allocation = allocate_cents(variant, units)
                    score = score_allocation(allocation, variant, config)
                    feasible.append((score["estimated_revenue"], variant, allocation))
        if not feasible:
            raise ForecastSupportError(
                "This budget is feasible, but no supported active-platform mix can forecast it."
            )
        _, curves, allocation = max(feasible, key=lambda item: item[0])
        totals = score_allocation(allocation, curves, config)
        if totals["budget"] != config.budget or not math.isfinite(totals["estimated_revenue"]):
            raise DomainError("The plan did not pass exact-total checks. No plan was saved.", 409)
        comparisons = []
        for name, weights in [
            ("Constrained equal split", {p: 1 for p in contexts}),
            (
                "Constrained historical spend mix",
                {p: c["historical_spend"] for p, c in contexts.items()},
            ),
        ]:
            comparison = score_allocation(comparison_cents(curves, units, weights), curves, config)
            comparison["name"] = name
            comparison["estimated_difference"] = (
                totals["estimated_revenue"] - comparison["estimated_revenue"]
            )
            comparisons.append(comparison)
        context_evidence = []
        curve_evidence = []
        for platform, context in contexts.items():
            curve = curves[platform]
            context_evidence.append(
                {
                    "platform": platform,
                    "representative_date": context["date"],
                    "campaign_segment_rows_per_day": len(context["rows"]),
                    "supported_min": context["supported_min"],
                    "supported_max": context["supported_max"],
                    "campaign_day_spend_min": context["row_spend_min"],
                    "campaign_day_spend_max": context["row_spend_max"],
                    "reference_budget": context["reference_budget"],
                    "context_weights": [
                        {**{key: str(row[key]) for key in CATEGORICAL}, "weight": float(weight)}
                        for (_, row), weight in zip(
                            context["rows"].iterrows(), context["weights"], strict=True
                        )
                    ],
                }
            )
            curve_evidence.append(
                {
                    "platform": platform,
                    "points": [
                        {
                            "budget": int(curve["points"][i]) / 100,
                            "raw_revenue": float(raw),
                            "adjusted_revenue": float(adjusted),
                        }
                        for i, (raw, adjusted) in enumerate(
                            zip(curve["raw"], curve["adjusted"], strict=True)
                        )
                    ],
                }
            )
        check()
        report = {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": (requested or config).model_dump(mode="json"),
            "dataset": source.model_dump(mode="json"),
            "source_sha256": source_hash,
            "is_synthetic": source.is_synthetic,
            "forecast_status": "model" if job else "baseline" if assessment else "historical",
            "forecast_reasons": [],
            "baseline_assessment": assessment,
            "method_label": f"{job['result']['algorithm']} + adjusted response curves"
            if job
            else "Baseline-based estimate · evaluated error, assumed saturation · no ML"
            if assessment
            else "Historical-rule heuristic · assumed saturation · no ML",
            "model_id": config.model_id if job else None,
            "model_evidence": {
                "algorithm": job["result"]["algorithm"],
                "acceptance": job["result"]["acceptance"],
                "test": job["result"]["test"],
                "hashes": job["result"]["hashes"],
                "versions": job["result"]["versions"],
            }
            if job
            else None,
            "policy": POLICY,
            "currency": "PKR",
            "period_days": period_days,
            "curve_sample_step": config.sample_step_cents / 100,
            "objective": "Maximize adjusted estimated attributed revenue",
            "planning_end": (
                config.start_date + timedelta(days=config.horizon_days - 1)
            ).isoformat(),
            "training_period": {"start": str(training.date.min()), "end": str(training.date.max())},
            "training_controls": {
                **training_config.model_dump(mode="json"),
                "label_lag_days": coverage["label_lag_days"],
                "configured_label_lag_days": training_config.label_lag_days,
            },
            "coverage": coverage,
            "baseline": baseline,
            "totals": {k: v for k, v in totals.items() if k != "allocations"},
            "allocations": totals["allocations"],
            "comparisons": comparisons,
            "contexts": context_evidence,
            "user_limits": effective_limits(config),
            "curves": curve_evidence,
            "uncertainty": "Not quantified",
            "notice": "Simulated estimate — not a real-world revenue guarantee"
            if source.is_synthetic
            else "Advisory estimate; real-business performance is unverified.",
            "limitations": LIMITATIONS
            + [
                "Allocation is exact to PKR 0.01. Curve sampling is bounded to 200 intervals "
                "per budget; intermediate estimates use piecewise-linear interpolation.",
                "No conversions forecast is available; only revenue is modeled.",
            ]
            + (
                [
                    "Historical heuristic uses all mature history and assumed "
                    "saturation curve. Small samples can be unstable."
                ]
                if not job
                else []
            ),
            "prediction_rows": work_rows if job else 0,
            "elapsed_seconds": time.monotonic() - started,
        }
        return PlanStore(repo.root).save(report)


def get_plan(repo, plan_id):
    report = PlanStore(repo.root).get(plan_id)
    selected_source(repo, report["dataset"]["id"])
    return report


def export_plan(report, format):
    if format == "json":
        return json.dumps(report, indent=2, allow_nan=False)
    if format != "csv":
        raise DomainError("Choose CSV or JSON for the budget plan export.")
    buffer = io.StringIO()
    fields = [
        "plan_id",
        "dataset_id",
        "source",
        "is_synthetic",
        "method",
        "model_id",
        "start_date",
        "horizon_days",
        "currency",
        "total_budget",
        "step",
        "platform",
        "budget",
        "share_percent",
        "estimated_revenue",
        "raw_estimated_revenue",
        "effective_min",
        "effective_max",
        "notice",
        "uncertainty",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for allocation in report["allocations"]:
        row = {
            "plan_id": report["id"],
            "dataset_id": report["dataset"]["id"],
            "source": report["dataset"]["source"],
            "is_synthetic": report["is_synthetic"],
            "method": report["method_label"],
            "model_id": report["model_id"],
            "start_date": report["config"]["start_date"],
            "horizon_days": report["config"]["horizon_days"],
            "currency": "PKR",
            "total_budget": report["config"]["budget"],
            "step": report["config"]["step"],
            "notice": report["notice"],
            "uncertainty": report["uncertainty"],
            **{key: value for key, value in allocation.items() if key in fields},
        }
        writer.writerow({key: safe_csv_cell(value) for key, value in row.items()})
    return buffer.getvalue()


def create_plan(repo, config):
    from ads_optimizer.optimization.planning import create_plan as plan

    return plan(repo, config)
