"""Hand-crafted OHLC sequences for deterministic zone-detection tests.

`demand_sequence()` builds: a few quiet candles -> a swing high at index 6
-> more quiet candles -> a 3-candle base (indices 13-15) -> a bullish
displacement candle at index 16 that breaks the swing high at 102.0,
creating a Demand zone with boundaries [100.8, 101.7] -> a pullback that
interacts with the zone WITHOUT confirming (index 19, bearish close) ->
a confirming bullish candle at index 20 that closes back above 101.7.

`supply_sequence()` is the exact mirror image (negated around 100).
"""
from __future__ import annotations

import pandas as pd


def _rows_to_df(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["timestamp"] = pd.date_range("2024-01-01", periods=len(df), freq="30min")
    df["volume"] = 0.0
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def demand_sequence():
    rows = [
        (100.0, 100.5, 99.5, 100.0),   # 0
        (100.0, 100.5, 99.6, 100.1),   # 1
        (100.1, 100.6, 99.7, 100.2),   # 2
        (100.2, 100.7, 99.8, 100.3),   # 3
        (100.3, 100.8, 99.9, 100.2),   # 4
        (100.2, 100.7, 99.8, 100.1),   # 5
        (100.1, 102.0, 100.0, 101.8),  # 6  <- swing high (high=102.0)
        (101.8, 101.9, 101.3, 101.5),  # 7
        (101.5, 101.7, 101.0, 101.2),  # 8
        (101.2, 101.7, 100.9, 101.3),  # 9
        (101.3, 101.8, 101.0, 101.4),  # 10
        (101.4, 101.9, 101.1, 101.3),  # 11
        (101.3, 101.8, 101.0, 101.2),  # 12
        (101.2, 101.7, 100.9, 101.1),  # 13  base candle 1
        (101.1, 101.6, 100.8, 101.15), # 14  base candle 2
        (101.15, 101.65, 100.85, 101.2),  # 15  base candle 3 -> [lower=100.8, upper=101.7]
        (101.2, 104.35, 101.15, 104.0),   # 16  bullish displacement, closes 104.0 > 102.0 swing
        (104.0, 104.1, 103.0, 103.2),  # 17  pullback (no interaction yet)
        (103.2, 103.3, 101.9, 102.0),  # 18  still above zone (low=101.9 > 101.7)
        (102.0, 102.1, 101.0, 101.2),  # 19  interacts (low<=101.7,high>=100.8) but bearish -> no confirm
        (101.2, 102.0, 101.1, 101.9),  # 20  interacts AND confirms (bullish, closes > 101.7)
        (101.9, 102.0, 101.5, 101.8),  # 21  (entry candle for the resulting BUY)
    ]
    return _rows_to_df(rows)


def _negate(rows, axis=200.0):
    # mirror a sequence around `axis` and swap high/low so it becomes the
    # bearish mirror image (open/close/high/low relationships preserved).
    out = []
    for o, h, l, c in rows:
        out.append((axis - o, axis - l, axis - h, axis - c))
    return out


def supply_sequence():
    demand_rows = [
        (100.0, 100.5, 99.5, 100.0), (100.0, 100.5, 99.6, 100.1), (100.1, 100.6, 99.7, 100.2),
        (100.2, 100.7, 99.8, 100.3), (100.3, 100.8, 99.9, 100.2), (100.2, 100.7, 99.8, 100.1),
        (100.1, 102.0, 100.0, 101.8), (101.8, 101.9, 101.3, 101.5), (101.5, 101.7, 101.0, 101.2),
        (101.2, 101.7, 100.9, 101.3), (101.3, 101.8, 101.0, 101.4), (101.4, 101.9, 101.1, 101.3),
        (101.3, 101.8, 101.0, 101.2), (101.2, 101.7, 100.9, 101.1), (101.1, 101.6, 100.8, 101.15),
        (101.15, 101.65, 100.85, 101.2), (101.2, 104.35, 101.15, 104.0), (104.0, 104.1, 103.0, 103.2),
        (103.2, 103.3, 101.9, 102.0), (102.0, 102.1, 101.0, 101.2), (101.2, 102.0, 101.1, 101.9),
        (101.9, 102.0, 101.5, 101.8),
    ]
    rows = _negate(demand_rows, axis=200.0)
    return _rows_to_df(rows)
