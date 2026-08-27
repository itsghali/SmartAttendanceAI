"""Objective swing-high / swing-low detection with an explicit no-look-ahead
confirmation delay.

Definition (SWING_LOOKBACK = k):
    candle i is a RAW swing high  iff high[i] > high[j] for all j in
        [i-k, i-1] and high[i] > high[j] for all j in [i+1, i+k]   (strict).
    candle i is a RAW swing low   iff low[i]  < low[j]  for all j in
        [i-k, i-1] and low[i]  < low[j]  for all j in [i+1, i+k]   (strict).

A swing at index i can only be DETECTED once candle i+k has closed (we need
the k candles to its right to exist and be complete). We therefore attach a
`confirmed_at` index of i+k to every raw swing. Nothing in the strategy is
ever allowed to consult a swing whose confirmed_at is greater than the
"as of" index of the current decision — that is the mechanism that prevents
look-ahead bias. Ties (equal highs/lows) do not qualify as a swing; this is
a deterministic, documented choice (see README, "Resolved Ambiguities").
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SwingPoint:
    index: int          # index of the swing candle itself
    price: float
    confirmed_at: int    # index at which this swing becomes knowable


def compute_raw_swings(df: pd.DataFrame, lookback: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (is_swing_high, is_swing_low) boolean arrays, length == len(df).

    Purely a function of price data; does NOT encode when the information
    becomes available for trading decisions — see SwingRegistry for that.
    """
    n = len(df)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)

    for i in range(lookback, n - lookback):
        left_h = high[i - lookback:i]
        right_h = high[i + 1:i + lookback + 1]
        if high[i] > left_h.max() and high[i] > right_h.max():
            is_high[i] = True

        left_l = low[i - lookback:i]
        right_l = low[i + 1:i + lookback + 1]
        if low[i] < left_l.min() and low[i] < right_l.min():
            is_low[i] = True

    return is_high, is_low


class SwingRegistry:
    """Chronological-safe accessor for confirmed swing points.

    Usage in the backtest loop: at each processed index `t`, call
    `confirmed_highs_as_of(t)` / `confirmed_lows_as_of(t)` to get every swing
    point whose existence is knowable using only candles that have closed by
    index t (inclusive). Internally this is a cheap pointer advance, not a
    re-scan, so the whole loop stays O(n).
    """

    def __init__(self, df: pd.DataFrame, lookback: int):
        self.lookback = lookback
        is_high, is_low = compute_raw_swings(df, lookback)
        high_prices = df["high"].to_numpy()
        low_prices = df["low"].to_numpy()

        self._highs: list[SwingPoint] = [
            SwingPoint(index=i, price=high_prices[i], confirmed_at=i + lookback)
            for i in np.nonzero(is_high)[0]
        ]
        self._lows: list[SwingPoint] = [
            SwingPoint(index=i, price=low_prices[i], confirmed_at=i + lookback)
            for i in np.nonzero(is_low)[0]
        ]
        # confirmed_at is monotonically increasing within each list because
        # index is, so bisect gives an O(log n) instead of O(n) lookup.
        self._high_confirmed_at = [s.confirmed_at for s in self._highs]
        self._low_confirmed_at = [s.confirmed_at for s in self._lows]

    def confirmed_highs_as_of(self, t: int) -> list[SwingPoint]:
        idx = bisect.bisect_right(self._high_confirmed_at, t)
        return self._highs[:idx]

    def confirmed_lows_as_of(self, t: int) -> list[SwingPoint]:
        idx = bisect.bisect_right(self._low_confirmed_at, t)
        return self._lows[:idx]

    def last_confirmed_high_as_of(self, t: int) -> SwingPoint | None:
        idx = bisect.bisect_right(self._high_confirmed_at, t)
        return self._highs[idx - 1] if idx > 0 else None

    def last_confirmed_low_as_of(self, t: int) -> SwingPoint | None:
        idx = bisect.bisect_right(self._low_confirmed_at, t)
        return self._lows[idx - 1] if idx > 0 else None
