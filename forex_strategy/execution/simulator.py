"""Bar-by-bar SL/TP exit simulation, strictly forward in time from the entry
candle (section 21: same-candle SL/TP ambiguity).

Only OHLC is available, so when both SL and TP fall inside the same
candle's [low, high] range we cannot know which was touched first from the
candle alone. SAME_CANDLE_POLICY resolves this deterministically:
    SL_FIRST -> assume the adverse outcome (conservative, the default)
    TP_FIRST -> assume the favorable outcome (optimistic upper bound)
Reporting both is how the spec wants robustness checked (section 21).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    END_OF_DATA = "END_OF_DATA"


@dataclass(frozen=True)
class ExitResult:
    exit_index: int
    exit_timestamp: pd.Timestamp
    exit_price_raw: float
    exit_reason: ExitReason


def simulate_exit(
    df: pd.DataFrame,
    entry_index: int,
    direction: str,
    sl: float,
    tp: float,
    same_candle_policy: str = "SL_FIRST",
) -> ExitResult:
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]
    timestamps = df["timestamp"]
    n = len(df)

    for j in range(entry_index, n):
        h, l = highs.iat[j], lows.iat[j]
        if direction == "BUY":
            hit_sl = l <= sl
            hit_tp = h >= tp
        else:
            hit_sl = h >= sl
            hit_tp = l <= tp

        if hit_sl and hit_tp:
            if same_candle_policy == "SL_FIRST":
                return ExitResult(j, timestamps.iat[j], sl, ExitReason.STOP_LOSS)
            return ExitResult(j, timestamps.iat[j], tp, ExitReason.TAKE_PROFIT)
        if hit_sl:
            return ExitResult(j, timestamps.iat[j], sl, ExitReason.STOP_LOSS)
        if hit_tp:
            return ExitResult(j, timestamps.iat[j], tp, ExitReason.TAKE_PROFIT)

    last = n - 1
    return ExitResult(last, timestamps.iat[last], float(closes.iat[last]), ExitReason.END_OF_DATA)
