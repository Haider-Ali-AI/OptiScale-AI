"""Reproducible campaign/day observations with spend-driven funnel and saturation."""

import numpy as np
import pandas as pd

from ads_optimizer.domain import GenerateConfig

SIMULATOR_VERSION = "1.0"


def generate_frame(config: GenerateConfig) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(config.seed)
    days = (config.end_date - config.start_date).days + 1
    n = config.rows
    campaign_count = max(int(np.ceil(n / days)), len(config.platforms))
    campaign_index = np.arange(n) % campaign_count
    day_index = (np.arange(n) // campaign_count) * (days - 1) // max((n - 1) // campaign_count, 1)
    # Platform exposure differs by campaign; targeting stays known before each day.
    weights = np.array([1 + (5 - i) * 0.15 for i in range(len(config.platforms))])
    channel = rng.choice(len(weights), campaign_count, p=weights / weights.sum())
    channel[: len(weights)] = rng.permutation(len(weights))
    channel_rows = channel[campaign_index]
    platforms = np.array(config.platforms)[channel_rows]
    campaign_quality = rng.lognormal(0, 0.25, campaign_count)[campaign_index]
    season = 1 + 0.12 * np.sin(2 * np.pi * day_index / 30)
    fatigue = np.exp(-day_index / 450)
    spend = np.round(rng.lognormal(7.3, 0.55, n) * (1 + channel_rows * 0.08), 2)
    cpm = 210 + channel_rows * 35
    # Delivery costs and funnel response worsen with spend: diminishing marginal returns.
    impressions = rng.poisson(spend * 1000 / cpm / (1 + spend / 18_000))
    ctr = np.clip(0.021 * campaign_quality * season * fatigue / (1 + spend / 10_000), 0.002, 0.12)
    clicks = rng.binomial(impressions, ctr)
    conversion_rate = np.clip(
        (0.035 + channel_rows * 0.004) * season * campaign_quality, 0.002, 0.3
    )
    conversions = rng.binomial(clicks, conversion_rate)
    revenue = np.zeros(n)
    positive = conversions > 0
    aov = 2400 + channel_rows * 220
    revenue[positive] = rng.gamma(conversions[positive] * 4, aov[positive] / 4)
    campaign_names = np.array([f"Campaign {i + 1:03d}" for i in range(campaign_count)])
    frame = pd.DataFrame(
        {
            "date": (
                pd.Timestamp(config.start_date) + pd.to_timedelta(day_index, unit="D")
            ).strftime("%Y-%m-%d"),
            "campaign": campaign_names[campaign_index],
            "platform": platforms,
            "impressions": impressions,
            "clicks": clicks,
            "spend": spend,
            "conversions": conversions,
            "revenue": np.round(revenue, 2),
            "age": rng.choice(["18–24", "25–34", "35–44", "45–54"], campaign_count)[campaign_index],
            "gender": rng.choice(["female", "male", "all"], campaign_count)[campaign_index],
            "city": rng.choice(
                ["Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad"], campaign_count
            )[campaign_index],
            "device": rng.choice(
                ["mobile", "desktop", "tablet"], campaign_count, p=[0.8, 0.17, 0.03]
            )[campaign_index],
            "campaign_id": [f"sim-{i + 1:04d}" for i in campaign_index],
            "account_id": "synthetic-local",
            "currency": "PKR",
            "is_synthetic": True,
            "conversion_definition": "click-attributed purchases",
            "attribution_window": "synthetic same-day click",
        }
    )
    # Kept in a separate evaluation-only file, never a training/inference feature column.
    truth = {
        "simulator_version": SIMULATOR_VERSION,
        "config": config.model_dump(mode="json"),
        "cpm_base": 210,
        "delivery_saturation": 18000,
        "click_saturation": 10000,
        "season_period_days": 30,
        "fatigue_decay_days": 450,
    }
    return frame, truth
