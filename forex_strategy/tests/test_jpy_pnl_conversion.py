"""Regression test for a real bug caught during development: GBP/JPY P&L is
computed in JPY (price_diff * units) but the account equity is USD. Without
converting through usdjpy_conversion_rate, a losing GBP/JPY trade was
inflated by ~100x (e.g. a $1,000 intended risk producing a $150,000+ loss).
"""
from __future__ import annotations

import pandas as pd

from backtest.engine import run_pair_backtest
from risk.position_sizing import quote_to_usd_factor
from strategy.signals import SetupOutcome
from zones.lifecycle import Zone, ZoneType


def _minimal_cfg():
    return {
        "pairs": {"GBPJPY": {"pip_size": 0.01}},
        "transaction_costs": {"GBPJPY": {"spread_pips": 0.0, "slippage_pips": 0.0}},
        "commission_per_lot_round_turn": 0.0,
        "initial_capital": 100_000,
        "risk_per_trade": 0.01,
        "lot_size": 100_000,
        "lot_step": 0.01,
        "min_lot": 0.01,
        "usdjpy_conversion_rate": 150.0,
        "max_open_trades_per_pair": 1,
        "same_candle_policy": "SL_FIRST",
    }


def test_quote_to_usd_factor_only_applies_to_jpy_crosses():
    assert quote_to_usd_factor("EURUSD", 150.0) == 1.0
    assert abs(quote_to_usd_factor("GBPJPY", 150.0) - (1 / 150.0)) < 1e-12


def test_gbpjpy_stop_loss_realizes_approximately_one_r_not_150x():
    cfg = _minimal_cfg()
    n = 5
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="30min"),
        "open": [164.60, 164.62, 165.00, 165.00, 165.00],
        "high": [164.65, 164.63, 165.10, 165.00, 165.00],
        "low": [164.55, 164.61, 164.60, 165.00, 165.00],
        "close": [164.60, 164.62, 164.90, 165.00, 165.00],
    })
    zone = Zone(
        zone_id=1, zone_type=ZoneType.SUPPLY, upper=164.60, lower=164.50,
        base_start_index=0, base_end_index=0, displacement_index=1, created_index=1,
        atr_at_creation=0.10,
    )
    # A SELL that gets stopped out on candle index 2 (high=165.10 >= sl=164.71)
    setup = SetupOutcome(
        pair="GBPJPY", direction="SELL", zone=zone,
        confirmation_index=1, confirmation_timestamp=df["timestamp"].iat[1],
        entry_index=2, entry_timestamp=df["timestamp"].iat[2],
        raw_entry=164.62, sl=164.71, tp=163.00,
        sl_pips=9.0, tp_pips=162.0, rr=18.0,
        atr_at_confirmation=0.10, ma200_at_confirmation=163.00,
        accepted=True, rejection_reasons=[],
    )

    result = run_pair_backtest("GBPJPY", df, cfg, [setup])
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "STOP_LOSS"

    # With zero transaction costs, the realized loss should be (very close
    # to) exactly the intended risk_amount — never 100x+ larger.
    assert abs(abs(trade.pnl) - trade.risk_amount) < 1.0
