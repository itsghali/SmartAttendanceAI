"""Average True Range (Wilder's smoothing).

ATR[i] is computed using only candles with index <= i, so it is safe to use
the moment candle i closes. It must never be referenced for decisions made
before candle i has closed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ATR.

    ATR[period-1] = simple mean of TR[0..period-1].
    ATR[i] = (ATR[i-1] * (period-1) + TR[i]) / period   for i >= period.
    ATR[i] is NaN for i < period-1 (not enough data yet — no trades may use
    it before this point).
    """
    tr = true_range(df)
    result = np.full(len(df), np.nan)

    if len(df) < period:
        return pd.Series(result, index=df.index)

    result[period - 1] = tr.iloc[0:period].mean()
    for i in range(period, len(df)):
        result[i] = (result[i - 1] * (period - 1) + tr.iloc[i]) / period

    return pd.Series(result, index=df.index)
