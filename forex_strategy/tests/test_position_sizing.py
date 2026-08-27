import pytest

from risk.position_sizing import pip_value_usd_per_lot, size_position


def test_pip_value_usd_pairs_quoted_in_usd():
    # EUR/USD, GBP/USD, AUD/USD: pip 0.0001, 100k lot -> $10/pip/lot
    pv = pip_value_usd_per_lot("EURUSD", pip_size=0.0001, lot_size=100_000, usdjpy_rate=150.0)
    assert abs(pv - 10.0) < 1e-9


def test_pip_value_usd_gbpjpy_converted_via_usdjpy_rate():
    # GBP/JPY: pip 0.01, 100k lot -> 1000 JPY/pip -> USD via usdjpy_rate
    pv = pip_value_usd_per_lot("GBPJPY", pip_size=0.01, lot_size=100_000, usdjpy_rate=150.0)
    assert abs(pv - (1000.0 / 150.0)) < 1e-9


def test_risk_amount_is_exactly_percentage_of_equity():
    result = size_position(
        account_equity=100_000, risk_per_trade=0.01, sl_distance_pips=10,
        pair="EURUSD", pip_size=0.0001, lot_size=100_000, lot_step=0.01, min_lot=0.01,
        usdjpy_rate=150.0,
    )
    assert abs(result.risk_amount - 1_000.0) < 1e-9


def test_position_size_matches_risk_amount_over_pip_distance_times_pip_value():
    result = size_position(
        account_equity=100_000, risk_per_trade=0.01, sl_distance_pips=10,
        pair="EURUSD", pip_size=0.0001, lot_size=100_000, lot_step=0.01, min_lot=0.01,
        usdjpy_rate=150.0,
    )
    # risk_amount=1000, pip_value=$10/lot, sl=10 pips -> raw lots = 1000/(10*10)=10.0
    assert abs(result.lots - 10.0) < 1e-9
    assert abs(result.units - 1_000_000) < 1e-6


def test_lots_are_rounded_down_to_broker_step_never_up():
    result = size_position(
        account_equity=1_000, risk_per_trade=0.01, sl_distance_pips=17,
        pair="EURUSD", pip_size=0.0001, lot_size=100_000, lot_step=0.01, min_lot=0.01,
        usdjpy_rate=150.0,
    )
    # risk_amount=10, pip_value=10 -> raw lots = 10/(17*10)=0.0588 -> floor to 0.05
    assert result.lots <= 0.0588 + 1e-9
    assert abs(result.lots - 0.05) < 1e-9


def test_zero_sl_distance_is_rejected():
    with pytest.raises(ValueError):
        size_position(
            account_equity=100_000, risk_per_trade=0.01, sl_distance_pips=0,
            pair="EURUSD", pip_size=0.0001, lot_size=100_000, lot_step=0.01, min_lot=0.01,
            usdjpy_rate=150.0,
        )
