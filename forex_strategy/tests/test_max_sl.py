import pandas as pd

from risk.risk_reward import check_max_sl_pips
from strategy.signals import RejectionReason, _evaluate_setup
from zones.lifecycle import Zone, ZoneType


def test_sl_within_limit_passes():
    assert check_max_sl_pips(sl_distance_pips=15.0, max_sl_pips=20)
    assert check_max_sl_pips(sl_distance_pips=20.0, max_sl_pips=20)  # boundary inclusive


def test_sl_beyond_limit_fails():
    assert not check_max_sl_pips(sl_distance_pips=22.0, max_sl_pips=20)
    assert not check_max_sl_pips(sl_distance_pips=15.01, max_sl_pips=15)


def test_worked_example_from_spec_section_14():
    # Entry = 1.16500, structural SL = 1.16280 -> distance = 22 pips,
    # MAX_SL_PIPS = 20 -> must be rejected, and the SL price itself must be
    # left untouched (never moved closer to price).
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=2, freq="30min"),
        "open": [1.16000, 1.16500], "high": [1.16600, 1.16600],
        "low": [1.16200, 1.16200], "close": [1.16500, 1.16500],
    })
    zone = Zone(
        zone_id=1, zone_type=ZoneType.DEMAND, upper=1.16350, lower=1.16300,
        base_start_index=0, base_end_index=1, displacement_index=2, created_index=2,
        atr_at_creation=0.00200,
    )
    setup = _evaluate_setup(
        pair="EURUSD", direction="BUY", zone=zone, i=0, df=df, timestamps=df["timestamp"],
        atr_at_confirmation=0.00200, ma200_at_confirmation=1.17000, pip_size=0.0001,
        sl_buffer_atr_multiplier=0.10, max_sl_pips=20, min_rr=1.0,
    )
    assert abs(setup.sl - 1.16280) < 1e-9
    assert round(setup.sl_pips) == 22
    assert not setup.accepted
    assert RejectionReason.SL_TOO_LARGE in setup.rejection_reasons
