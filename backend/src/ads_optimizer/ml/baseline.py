"""Independent chronological screen for a simple historical statistical baseline."""

import numpy as np

from ads_optimizer.ml.evaluate import baseline_predict, fit_baseline, metrics


def assess_baseline(parts):
    training, validation, test = parts
    baseline = fit_baseline(training)
    mean = float(training.revenue.mean())
    reasons, results = [], {}
    for name, frame in [("validation", validation), ("test", test)]:
        prediction = baseline_predict(frame, baseline)
        score = metrics(frame.revenue, prediction)
        reference = metrics(frame.revenue, np.full(len(frame), mean))
        results[name] = {"baseline": score, "constant_mean": reference}
        if score["wape"] is None or score["wape"] > 1:
            reasons.append(f"Baseline {name} WAPE must be defined and at most 100%.")
        for platform, rows in frame.groupby("platform"):
            train_rows = training[training.platform == platform]
            if len(train_rows) < 20 or len(rows) < 5:
                reasons.append(f"{platform} lacks baseline temporal support.")
                continue
            mask = frame.platform.eq(platform).to_numpy()
            local = metrics(rows.revenue, prediction[mask])
            constant = metrics(rows.revenue, np.full(len(rows), float(train_rows.revenue.mean())))
            if local["rmse"] >= constant["rmse"] and local["rmse"] > 0:
                reasons.append(
                    f"{platform} baseline {name} RMSE does not beat a train-mean predictor."
                )
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "metrics": results,
        "baseline": baseline,
        "policy": "baseline-v1: chronological 180/60/60 rows, per-platform 20/5/5, "
        "WAPE ≤100% and RMSE better than train-mean on validation and test. "
        "An operational screen, not statistical confidence or causal validation.",
    }
