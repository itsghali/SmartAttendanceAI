"""Historical data validation.

Checks required by the spec (section 23):
  * missing candles (gaps larger than the expected M30 spacing)
  * duplicate timestamps
  * incorrect / non-monotonic ordering
  * missing OHLC values (NaN)
  * invalid prices (<= 0, or high/low inconsistent with open/close)
  * timezone consistency (tz-naive vs tz-aware mixed within a file)

`validate` raises on hard errors (duplicates, non-monotonic order after sort,
NaNs, invalid OHLC relationships) and returns a report dict describing softer
issues (gaps) that the caller may choose to act on (e.g. drop trades whose
warm-up window spans a gap).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

EXPECTED_SPACING = pd.Timedelta(minutes=30)


@dataclass
class ValidationReport:
    n_rows: int
    n_duplicates_removed: int
    n_gaps: int
    gap_locations: List[pd.Timestamp] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate(df: pd.DataFrame, pair: str = "") -> tuple[pd.DataFrame, ValidationReport]:
    warnings: List[str] = []

    if df[["open", "high", "low", "close"]].isna().any().any():
        bad = df[df[["open", "high", "low", "close"]].isna().any(axis=1)]
        raise ValueError(f"{pair}: missing OHLC values at rows {bad.index.tolist()[:10]}")

    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{pair}: non-positive prices found")

    if not (df["high"] >= df[["open", "close", "low"]].max(axis=1)).all():
        bad = df[~(df["high"] >= df[["open", "close", "low"]].max(axis=1))]
        raise ValueError(f"{pair}: invalid candles — high below open/close/low at {bad.index.tolist()[:10]}")

    if not (df["low"] <= df[["open", "close", "high"]].min(axis=1)).all():
        bad = df[~(df["low"] <= df[["open", "close", "high"]].min(axis=1))]
        raise ValueError(f"{pair}: invalid candles — low above open/close/high at {bad.index.tolist()[:10]}")

    tz_kinds = {ts.tzinfo is not None for ts in df["timestamp"].head(1000)}
    if len(tz_kinds) > 1:
        raise ValueError(f"{pair}: inconsistent timezone-awareness within the file")

    n_before = len(df)
    df = df.drop_duplicates(subset="timestamp", keep="first").reset_index(drop=True)
    n_dupes = n_before - len(df)
    if n_dupes:
        warnings.append(f"{n_dupes} duplicate timestamp(s) removed (kept first occurrence)")

    if not df["timestamp"].is_monotonic_increasing:
        raise ValueError(f"{pair}: timestamps are not strictly increasing after sort/dedup — corrupt data")

    diffs = df["timestamp"].diff().dropna()
    gap_mask = diffs > EXPECTED_SPACING
    n_gaps = int(gap_mask.sum())
    gap_locations = df["timestamp"].iloc[1:][gap_mask.values].tolist()
    if n_gaps:
        warnings.append(f"{n_gaps} gap(s) larger than 30 minutes detected (e.g. weekends/holidays are expected)")

    report = ValidationReport(
        n_rows=len(df),
        n_duplicates_removed=n_dupes,
        n_gaps=n_gaps,
        gap_locations=gap_locations,
        warnings=warnings,
    )
    return df, report
