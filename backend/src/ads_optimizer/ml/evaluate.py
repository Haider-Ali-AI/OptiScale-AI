import numpy as np


def metrics(actual, predicted):
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    error = actual - predicted
    denominator = float(np.abs(actual).sum())
    variance = float(np.square(actual - actual.mean()).sum())
    return {
        "r2": float(1 - np.square(error).sum() / variance)
        if len(actual) > 1 and variance > 0
        else None,
        "rows": len(actual),
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt(np.square(error).mean())),
        "wape": float(np.abs(error).sum() / denominator) if denominator else None,
    }


def fit_baseline(frame):
    global_rate = float(frame.revenue.sum() / frame.spend.sum())
    prior_spend = float(frame.spend.mean() * 20)
    return {
        "global_rate": global_rate,
        "platform_rates": {
            str(platform): float(
                (part.revenue.sum() + prior_spend * global_rate) / (part.spend.sum() + prior_spend)
            )
            for platform, part in frame.groupby("platform")
        },
        "prior_equivalent_rows": 20,
    }


def baseline_predict(frame, baseline):
    return frame.spend.to_numpy() * np.array(
        [baseline["platform_rates"].get(p, baseline["global_rate"]) for p in frame.platform]
    )


def evaluate(frame, prediction, baseline):
    base = baseline_predict(frame, baseline)
    result = {
        "model": metrics(frame.revenue, prediction),
        "baseline": metrics(frame.revenue, base),
        "platforms": [],
    }
    for platform in sorted(frame.platform.unique()):
        mask = (frame.platform == platform).to_numpy()
        result["platforms"].append(
            {
                "platform": str(platform),
                "model": metrics(frame.revenue[mask], prediction[mask]),
                "baseline": metrics(frame.revenue[mask], base[mask]),
            }
        )
    return result
