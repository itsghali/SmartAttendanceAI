"""Synthetic M30 OHLC data generator.

IMPORTANT: this is NOT real market data. No real historical Forex feed is
available in this execution environment, so this generator produces a
reproducible, regime-switching random walk (trending legs, quiet
consolidation legs, and occasional volatility spikes) purely so the rest of
the system — detection, filters, execution, metrics, reports — can be
demonstrated and unit-tested end to end.

For actual research use, replace the files under data/raw/ with real
broker/vendor M30 OHLC CSVs (same column schema: timestamp, open, high,
low, close[, volume]) and re-run main.py. Every conclusion drawn from the
synthetic dataset in outputs/ is a pipeline demonstration only and carries
no evidentiary value about the real strategy's edge.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PAIR_START_PRICE = {
    "EURUSD": 1.1000,
    "GBPUSD": 1.2700,
    "GBPJPY": 165.00,
    "AUDUSD": 0.6800,
}

# Distinct seeds per pair — each pair must be an INDEPENDENT random walk, not
# the same sequence rescaled by pip size/start price. Sharing one seed across
# pairs would make "backtest each pair independently" meaningless (identical
# trade counts/win rates up to scaling), which is exactly what section 2 of
# the spec warns against assuming.
PAIR_SEED = {
    "EURUSD": 42,
    "GBPUSD": 43,
    "GBPJPY": 44,
    "AUDUSD": 45,
}


def generate_synthetic_m30(
    pair: str,
    n_bars: int = 16000,
    pip_size: float = 0.0001,
    seed: int = 42,
    start_price: float | None = None,
    start_date: str = "2021-01-04",
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    price = start_price if start_price is not None else PAIR_START_PRICE.get(pair, 1.0000)

    # Build a Forex-market-hours timestamp index: 30-min bars, Mon 00:00 UTC
    # through Fri 23:30 UTC, skipping the Sat/Sun weekend close.
    timestamps = []
    ts = pd.Timestamp(start_date)
    while len(timestamps) < n_bars:
        if ts.weekday() < 5:  # Mon-Fri
            timestamps.append(ts)
        ts = ts + pd.Timedelta(minutes=30)
    timestamps = timestamps[:n_bars]

    pip = pip_size
    regime_len = 0
    drift = 0.0
    sigma = 3.0 * pip

    rows = []
    close_prev = price
    for i in range(n_bars):
        if regime_len <= 0:
            regime_len = int(rng.integers(80, 300))
            regime_type = rng.choice(["up", "down", "range"], p=[0.35, 0.35, 0.30])
            if regime_type == "up":
                drift = rng.uniform(0.05, 0.35) * pip
            elif regime_type == "down":
                drift = -rng.uniform(0.05, 0.35) * pip
            else:
                drift = 0.0
            sigma = rng.uniform(1.5, 4.0) * pip

        spike = rng.random() < 0.03
        step_sigma = sigma * (rng.uniform(5, 9) if spike else 1.0)
        step_drift = drift * (rng.uniform(3, 6) if spike else 1.0)

        change = rng.normal(step_drift, step_sigma)
        open_ = close_prev
        close = open_ + change

        wick_scale = step_sigma * 0.6
        high = max(open_, close) + abs(rng.normal(0, wick_scale))
        low = min(open_, close) - abs(rng.normal(0, wick_scale))
        low = max(low, pip)  # keep strictly positive

        rows.append((timestamps[i], open_, high, low, close, 0.0))
        close_prev = close
        regime_len -= 1

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    return df


def write_synthetic_dataset(path: str, pair: str, n_bars: int, pip_size: float, seed: int) -> None:
    df = generate_synthetic_m30(pair=pair, n_bars=n_bars, pip_size=pip_size, seed=seed)
    df.to_csv(path, index=False)
