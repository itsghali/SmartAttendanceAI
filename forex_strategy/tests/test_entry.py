import pandas as pd

from strategy.signals import RejectionReason, _evaluate_setup
from zones.lifecycle import Zone, ZoneType


def _df(entry_open: float):
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=2, freq="30min"),
        "open": [1.10000, entry_open],
        "high": [1.10100, entry_open + 0.0005],
        "low": [1.09900, entry_open - 0.0005],
        "close": [1.10050, entry_open],
    })


def _demand_zone():
    return Zone(
        zone_id=1, zone_type=ZoneType.DEMAND, upper=1.10040, lower=1.10000,
        base_start_index=0, base_end_index=1, displacement_index=2, created_index=2,
        atr_at_creation=0.0010,
    )


def _supply_zone():
    return Zone(
        zone_id=2, zone_type=ZoneType.SUPPLY, upper=1.10040, lower=1.10000,
        base_start_index=0, base_end_index=1, displacement_index=2, created_index=2,
        atr_at_creation=0.0010,
    )


def test_valid_demand_plus_confirmation_plus_ma200_above_yields_accepted_buy():
    df = _df(entry_open=1.10050)
    setup = _evaluate_setup(
        pair="EURUSD", direction="BUY", zone=_demand_zone(), i=0, df=df, timestamps=df["timestamp"],
        atr_at_confirmation=0.0010, ma200_at_confirmation=1.10200, pip_size=0.0001,
        sl_buffer_atr_multiplier=0.1, max_sl_pips=20, min_rr=1.0,
    )
    assert setup.accepted
    assert setup.direction == "BUY"
    assert setup.rr >= 1.0


def test_valid_supply_plus_confirmation_plus_ma200_below_yields_accepted_sell():
    df = _df(entry_open=1.09990)
    setup = _evaluate_setup(
        pair="EURUSD", direction="SELL", zone=_supply_zone(), i=0, df=df, timestamps=df["timestamp"],
        atr_at_confirmation=0.0010, ma200_at_confirmation=1.09800, pip_size=0.0001,
        sl_buffer_atr_multiplier=0.1, max_sl_pips=20, min_rr=1.0,
    )
    assert setup.accepted
    assert setup.direction == "SELL"
    assert setup.rr >= 1.0


def test_ma200_on_wrong_side_rejects_buy():
    df = _df(entry_open=1.10050)
    setup = _evaluate_setup(
        pair="EURUSD", direction="BUY", zone=_demand_zone(), i=0, df=df, timestamps=df["timestamp"],
        atr_at_confirmation=0.0010, ma200_at_confirmation=1.10000,  # below entry -> invalid TP for BUY
        pip_size=0.0001, sl_buffer_atr_multiplier=0.1, max_sl_pips=20, min_rr=1.0,
    )
    assert not setup.accepted
    assert RejectionReason.MA200_WRONG_SIDE in setup.rejection_reasons
