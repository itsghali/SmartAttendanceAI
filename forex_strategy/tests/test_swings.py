import pandas as pd

from zones.swings import SwingRegistry, compute_raw_swings


def _df_with_peak_at(peak_index: int, n: int, lookback: int):
    highs = [100.0] * n
    lows = [99.0] * n
    highs[peak_index] = 105.0
    return pd.DataFrame({
        "open": highs, "high": highs, "low": lows, "close": lows,
    })


def test_swing_high_detected_at_local_peak():
    lookback = 3
    df = _df_with_peak_at(peak_index=10, n=20, lookback=lookback)
    is_high, is_low = compute_raw_swings(df, lookback)
    assert is_high[10]
    assert not is_high[9]
    assert not is_high[11]


def test_swing_not_confirmed_before_enough_future_candles_exist():
    lookback = 3
    df = _df_with_peak_at(peak_index=10, n=20, lookback=lookback)
    registry = SwingRegistry(df, lookback)

    # The swing at index 10 requires candles 11,12,13 to have closed —
    # confirmed_at == 10 + lookback == 13.
    assert registry.confirmed_highs_as_of(12) == []
    confirmed_at_13 = registry.confirmed_highs_as_of(13)
    assert len(confirmed_at_13) == 1
    assert confirmed_at_13[0].index == 10


def test_no_look_ahead_swing_registry_matches_index_plus_lookback():
    lookback = 5
    df = _df_with_peak_at(peak_index=20, n=40, lookback=lookback)
    registry = SwingRegistry(df, lookback)
    swing = registry._highs[0]
    assert swing.confirmed_at == swing.index + lookback
