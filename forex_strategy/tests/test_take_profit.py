import pandas as pd

from risk.take_profit import take_profit_from_ma200, tp_direction_valid
from strategy.signals import _evaluate_setup
from zones.lifecycle import Zone, ZoneType


def test_take_profit_equals_ma200_at_confirmation():
    assert take_profit_from_ma200(1.16900) == 1.16900


def test_tp_direction_valid_buy_and_sell():
    assert tp_direction_valid("BUY", tp=1.1700, entry_price=1.1650)
    assert not tp_direction_valid("BUY", tp=1.1600, entry_price=1.1650)
    assert tp_direction_valid("SELL", tp=1.1600, entry_price=1.1650)
    assert not tp_direction_valid("SELL", tp=1.1700, entry_price=1.1650)


def test_tp_is_frozen_at_confirmation_ma200_not_recomputed_later():
    # Spec worked example: Entry=1.16500, MA200=1.16900 -> TP=1.16900, and it
    # must stay 1.16900 even if MA200 later moves to 1.17000.
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=2, freq="30min"),
        "open": [1.16000, 1.16500], "high": [1.16600, 1.16600],
        "low": [1.16200, 1.16200], "close": [1.16500, 1.16500],
    })
    zone = Zone(
        zone_id=1, zone_type=ZoneType.DEMAND, upper=1.16350, lower=1.16300,
        base_start_index=0, base_end_index=1, displacement_index=2, created_index=2,
        atr_at_creation=0.00050,
    )
    setup = _evaluate_setup(
        pair="EURUSD", direction="BUY", zone=zone, i=0, df=df, timestamps=df["timestamp"],
        atr_at_confirmation=0.00050, ma200_at_confirmation=1.16900, pip_size=0.0001,
        sl_buffer_atr_multiplier=0.10, max_sl_pips=20, min_rr=1.0,
    )
    assert setup.tp == 1.16900
    # A later MA200 value must never be consulted for this setup's TP.
    later_ma200 = 1.17000
    assert setup.tp != later_ma200
