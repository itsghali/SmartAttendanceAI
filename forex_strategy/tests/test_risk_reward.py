import pandas as pd

from risk.risk_reward import check_min_rr, compute_risk_reward
from strategy.signals import RejectionReason, _evaluate_setup
from zones.lifecycle import Zone, ZoneType


def test_compute_risk_reward_basic():
    risk, reward, rr = compute_risk_reward(entry=1.1650, sl=1.1630, tp=1.1690)
    assert abs(risk - 0.0020) < 1e-9
    assert abs(reward - 0.0040) < 1e-9
    assert abs(rr - 2.0) < 1e-9


def test_check_min_rr():
    assert check_min_rr(1.0, min_rr=1.0)   # boundary inclusive
    assert check_min_rr(2.0, min_rr=1.0)
    assert not check_min_rr(0.9, min_rr=1.0)
    assert not check_min_rr(float("nan"), min_rr=1.0)


def test_setup_below_min_rr_is_rejected():
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=2, freq="30min"),
        "open": [1.10000, 1.10050], "high": [1.10100, 1.10100],
        "low": [1.09900, 1.09900], "close": [1.10050, 1.10050],
    })
    zone = Zone(
        zone_id=1, zone_type=ZoneType.DEMAND, upper=1.10040, lower=1.10000,
        base_start_index=0, base_end_index=1, displacement_index=2, created_index=2,
        atr_at_creation=0.0010,
    )
    # tp barely above entry -> tiny reward relative to risk -> RR < 1.0
    setup = _evaluate_setup(
        pair="EURUSD", direction="BUY", zone=zone, i=0, df=df, timestamps=df["timestamp"],
        atr_at_confirmation=0.0010, ma200_at_confirmation=1.10060, pip_size=0.0001,
        sl_buffer_atr_multiplier=0.1, max_sl_pips=20, min_rr=1.0,
    )
    assert setup.rr < 1.0
    assert not setup.accepted
    assert RejectionReason.RR_INSUFFICIENT in setup.rejection_reasons
