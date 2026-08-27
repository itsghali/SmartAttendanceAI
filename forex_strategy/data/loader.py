"""Historical M30 OHLC(V) CSV loader.

Expected CSV columns (case-insensitive): timestamp, open, high, low, close,
volume (volume optional). Timestamps must be parseable and are assumed to be
in a single, consistent timezone for the whole file (see validator.py for the
consistency check).
"""
from __future__ import annotations

import pandas as pd

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close"]


def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing required columns {missing}")

    if "volume" not in df.columns:
        df["volume"] = 0.0

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=False)
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()

    # Sort chronologically up front. This is the ONE place we are allowed to
    # reorder rows — every downstream component then walks the frame strictly
    # in index order and must never peek ahead.
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df
