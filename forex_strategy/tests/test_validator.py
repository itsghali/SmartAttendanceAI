import pandas as pd
import pytest

from data.validator import validate


def _valid_df(n=10):
    ts = pd.date_range("2024-01-01", periods=n, freq="30min")
    return pd.DataFrame({
        "timestamp": ts, "open": 1.10, "high": 1.11, "low": 1.09, "close": 1.105, "volume": 0.0,
    })


def test_duplicate_timestamps_are_removed_and_reported():
    df = _valid_df(5)
    dup = pd.concat([df, df.iloc[[2]]], ignore_index=True)
    dup = dup.sort_values("timestamp").reset_index(drop=True)
    cleaned, report = validate(dup, pair="TEST")
    assert report.n_duplicates_removed == 1
    assert len(cleaned) == 5


def test_gap_is_detected_and_reported_not_raised():
    df = _valid_df(5)
    df.loc[3:, "timestamp"] = df.loc[3:, "timestamp"] + pd.Timedelta(hours=48)  # weekend-like gap
    df = df.sort_values("timestamp").reset_index(drop=True)
    cleaned, report = validate(df, pair="TEST")
    assert report.n_gaps == 1


def test_invalid_high_low_relationship_raises():
    df = _valid_df(3)
    df.loc[1, "high"] = 1.00  # high below close/open -> invalid candle
    with pytest.raises(ValueError):
        validate(df, pair="TEST")


def test_missing_ohlc_raises():
    df = _valid_df(3)
    df.loc[1, "close"] = float("nan")
    with pytest.raises(ValueError):
        validate(df, pair="TEST")
