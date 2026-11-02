"""Daily observation identity prefers stable campaign IDs over display names."""

import pandas as pd


def grain_frame(frame: pd.DataFrame) -> pd.DataFrame:
    keys = frame[["date", "platform", "age", "gender", "city", "device", "account_id"]].copy()
    keys["campaign_key"] = frame.campaign_id.where(frame.campaign_id.ne("unknown"), frame.campaign)
    return keys
