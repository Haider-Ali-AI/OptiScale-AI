"""Deterministic train-only preprocessing, validation selection, sealed later-date test."""

import json
import time

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from ads_optimizer.ml.baseline import assess_baseline
from ads_optimizer.ml.evaluate import baseline_predict, evaluate, fit_baseline, metrics
from ads_optimizer.ml.features import CATEGORICAL, FEATURES, encoder_for, transform
from ads_optimizer.ml.service import dependency_versions, sha256, split_summary

LIMITATIONS = [
    "Observed spend proxies planned spend; targeting must be known before the period.",
    "Temporal evaluation covers later dates, not unseen campaigns or causal budget uplift.",
    "Prediction uncertainty is not quantified. Attribution/selection bias and domain shift remain.",
    "Campaign × platform × day × reported segment is the prediction grain. Do not pass a whole "
    "platform budget as one campaign row; Budget Optimizer repeats a declared training-period mix.",
    "Campaign IDs, outcomes, lagged metrics and simulator truth are excluded from features.",
]


class Stopped(Exception):
    pass


def fit_model(train, validation, folder, seed, check):
    encoder = encoder_for(train)
    categories = [list(c) for c in encoder.categories_]
    (folder / "preprocessing.json").write_text(json.dumps({"categories": categories}))
    xtrain, xval = transform(train, encoder), transform(validation, encoder)
    candidates = []
    fallback_reason = None
    xgboost_loaded = False
    try:
        from xgboost import XGBRegressor
        from xgboost.callback import TrainingCallback

        xgboost_loaded = True

        class Guard(TrainingCallback):
            def after_iteration(self, model, epoch, evals_log):
                check()
                return False

        for depth in [3, 5]:
            check()
            parameters = dict(
                n_estimators=180,
                max_depth=depth,
                learning_rate=0.05,
                min_child_weight=10,
                reg_lambda=10,
                subsample=1,
                colsample_bytree=1,
                objective="reg:squarederror",
                tree_method="hist",
                n_jobs=2,
                random_state=seed,
            )
            model = XGBRegressor(**parameters, callbacks=[Guard()])
            model.fit(xtrain, train.revenue)
            candidates.append(
                (
                    metrics(validation.revenue, np.maximum(0, model.predict(xval)))["rmse"],
                    model,
                    parameters,
                )
            )
        algorithm = "XGBoost"
    except Exception as error:
        if xgboost_loaded:
            raise
        # Import/runtime incompatibility only. Failed fits are errors, never silently hidden.
        fallback_reason = (
            f"XGBoost could not load ({type(error).__name__}); using sklearn fallback."
        )
        check()
        parameters = dict(
            max_iter=180,
            max_leaf_nodes=15,
            learning_rate=0.05,
            l2_regularization=10,
            early_stopping=False,
            random_state=seed,
        )
        model = HistGradientBoostingRegressor(**parameters).fit(xtrain, train.revenue)
        check()
        candidates = [
            (
                metrics(validation.revenue, np.maximum(0, model.predict(xval)))["rmse"],
                model,
                parameters,
            )
        ]
        algorithm = "HistGradientBoostingRegressor"
    _, model, parameters = min(candidates, key=lambda candidate: candidate[0])
    if algorithm == "XGBoost":
        model.save_model(folder / "model.ubj")
        artifact = "model.ubj"
    else:
        # Never accepts uploads. Only our catalog's checksum-verified local artifact is loaded.
        joblib.dump(model, folder / "model.joblib")
        artifact = "model.joblib"
    return (
        model,
        encoder,
        {
            "algorithm": algorithm,
            "fallback_reason": fallback_reason,
            "parameters": parameters,
            "validation_candidates": [
                {"rmse": score, "parameters": params} for score, _, params in candidates
            ],
            "artifact": artifact,
        },
    )


def acceptance(validation, test, parts):
    reasons = []
    for name, result in [("Validation", validation), ("Holdout", test)]:
        if (
            result["baseline"]["rmse"] <= 0
            or result["model"]["rmse"] > 0.95 * result["baseline"]["rmse"]
        ):
            reasons.append(f"{name} RMSE must improve on the baseline by at least 5%.")
        if result["model"]["wape"] is None or result["model"]["wape"] > 1:
            reasons.append(f"{name} weighted absolute error must be defined and at most 100%.")
    for platform in sorted(set().union(*(set(p.platform) for p in parts))):
        counts = [int((p.platform == platform).sum()) for p in parts]
        if any(count < minimum for count, minimum in zip(counts, [20, 5, 5], strict=True)):
            reasons.append(f"{platform} needs 20 train / 5 validation / 5 test rows.")
        else:
            row = next(r for r in test["platforms"] if r["platform"] == platform)
            if row["model"]["rmse"] > 1.1 * row["baseline"]["rmse"]:
                reasons.append(f"{platform} holdout error exceeds baseline by more than 10%.")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "policy": "v1: ≥5% RMSE improvement on validation and test, WAPE ≤100%, "
        "platform support 20/5/5 and no platform test RMSE >110% of baseline.",
    }


def train(parts, coverage, manifest, config, folder, check, stage):
    started = time.perf_counter()
    training, validation, test = parts
    baseline = fit_baseline(training)
    check()
    stage("fitting", "Fitting train-only preprocessing and revenue models.")
    model, encoder, info = fit_model(training, validation, folder, config.seed, check)
    check()
    stage("evaluating", "Evaluating the selected model on later held-out dates.")
    predict = lambda frame: np.maximum(0, model.predict(transform(frame, encoder)))  # noqa: E731
    val_result, test_result = (evaluate(p, predict(p), baseline) for p in [validation, test])
    gates = acceptance(val_result, test_result, parts)
    predictions = predict(test)
    # Bounded diagnostic sample; the full holdout remains server-side.
    indices = np.linspace(0, len(test) - 1, min(60, len(test)), dtype=int)
    sample = [
        {
            "date": str(test.iloc[i].date),
            "platform": str(test.iloc[i].platform),
            "actual": float(test.iloc[i].revenue),
            "predicted": float(predictions[i]),
            "baseline": float(baseline_predict(test.iloc[[i]], baseline)[0]),
        }
        for i in indices
    ]
    names = encoder.get_feature_names_out(CATEGORICAL).tolist() + FEATURES[len(CATEGORICAL) :]
    importance = []
    if hasattr(model, "feature_importances_"):
        importance = sorted(
            [
                {"feature": name, "importance": float(value)}
                for name, value in zip(names, model.feature_importances_, strict=True)
            ],
            key=lambda item: item["importance"],
            reverse=True,
        )[:15]
    overlap = len(set(training.campaign) & set(test.campaign))
    result = {
        **info,
        "feature_schema_version": "campaign-context-v1",
        "features": FEATURES,
        "target": (
            "Synthetic revenue label (PKR). "
            if manifest.provenance_flags.get("revenue_is_synthetic")
            else "Same-period platform-attributed revenue (PKR). "
        )
        + "Conditioned on observed spend as a proxy for planned spend and pre-period context.",
        "grain": f"campaign × platform × {manifest.date_granularity} period × reported segment",
        "date_granularity": manifest.date_granularity,
        "splits": split_summary(parts),
        "coverage": coverage,
        "baseline": baseline,
        "validation": val_result,
        "test": test_result,
        "acceptance": gates,
        "baseline_assessment": assess_baseline(parts),
        "provenance_flags": manifest.provenance_flags,
        "spend_ranges": {
            str(p): {"min": float(g.spend.min()), "max": float(g.spend.max())}
            for p, g in training.groupby("platform")
        },
        "categories": [list(c) for c in encoder.categories_],
        "diagnostic_sample": sample,
        "feature_importance": importance,
        "campaign_overlap_count": overlap,
        "versions": dependency_versions(),
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": LIMITATIONS
        + (
            ["Synthetic labels/calendar: evaluation does not establish merchant accuracy."]
            if manifest.is_synthetic
            else ["Advertiser-reported labels; configured lag does not verify final conversions."]
        ),
        "recommendations_enabled": False,
        "recommendations_reason": "Budget Optimizer validates each plan separately; "
        "no live spending actions.",
        "uncertainty": "Not quantified",
        "hashes": {
            name: sha256(folder / name) for name in [info["artifact"], "preprocessing.json"]
        },
    }
    return result
