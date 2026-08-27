import pandas as pd

from execution.simulator import ExitReason, simulate_exit


def _df(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["timestamp"] = pd.date_range("2024-01-01", periods=len(df), freq="30min")
    return df


def test_same_candle_sl_first_policy_picks_sl():
    # candle 1 touches both SL (1.0980) and TP (1.1050) inside [low, high]
    df = _df([
        (1.1000, 1.1010, 1.0990, 1.1005),
        (1.1005, 1.1060, 1.0970, 1.1000),
    ])
    result = simulate_exit(df, entry_index=1, direction="BUY", sl=1.0980, tp=1.1050, same_candle_policy="SL_FIRST")
    assert result.exit_reason == ExitReason.STOP_LOSS
    assert result.exit_price_raw == 1.0980


def test_same_candle_tp_first_policy_picks_tp():
    df = _df([
        (1.1000, 1.1010, 1.0990, 1.1005),
        (1.1005, 1.1060, 1.0970, 1.1000),
    ])
    result = simulate_exit(df, entry_index=1, direction="BUY", sl=1.0980, tp=1.1050, same_candle_policy="TP_FIRST")
    assert result.exit_reason == ExitReason.TAKE_PROFIT
    assert result.exit_price_raw == 1.1050


def test_end_of_data_exit_when_neither_level_touched():
    df = _df([
        (1.1000, 1.1010, 1.0990, 1.1005),
        (1.1005, 1.1015, 1.0995, 1.1010),
    ])
    result = simulate_exit(df, entry_index=1, direction="BUY", sl=1.0900, tp=1.1200, same_candle_policy="SL_FIRST")
    assert result.exit_reason == ExitReason.END_OF_DATA
    assert result.exit_index == 1


def test_sell_direction_hit_sl_and_tp_conditions_are_mirrored():
    df = _df([
        (1.1000, 1.1010, 1.0990, 1.1005),
        (1.1005, 1.1060, 1.0940, 1.1000),
    ])
    result = simulate_exit(df, entry_index=1, direction="SELL", sl=1.1050, tp=1.0950, same_candle_policy="SL_FIRST")
    assert result.exit_reason == ExitReason.STOP_LOSS
