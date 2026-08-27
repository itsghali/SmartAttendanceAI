import pandas as pd

from indicators.moving_average import sma


def _df(n):
    return pd.DataFrame({
        "open": range(n), "high": range(n), "low": range(n), "close": list(range(1, n + 1)),
    })


def test_ma200_nan_before_warmup():
    df = _df(250)
    ma = sma(df, period=200)
    assert ma.iloc[:199].isna().all()


def test_ma200_value_uses_only_past_200_closes():
    df = _df(250)
    ma = sma(df, period=200)
    expected = sum(range(1, 201)) / 200  # closes 1..200 -> rows 0..199
    assert abs(ma.iloc[199] - expected) < 1e-9


def test_ma200_does_not_use_future_data():
    df = _df(250)
    ma_full = sma(df, period=200)
    # Truncate the dataframe right after the 200th close and recompute — the
    # value at index 199 must be identical, proving future rows played no role.
    truncated = df.iloc[:200].copy()
    ma_truncated = sma(truncated, period=200)
    assert abs(ma_full.iloc[199] - ma_truncated.iloc[199]) < 1e-9
