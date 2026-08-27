"""Chronological, single-pair backtest engine.

Consumes the setups produced by strategy/signals.py (already free of
look-ahead bias) and turns the ACCEPTED ones into simulated trades:
  - enforces `max_open_trades_per_pair` (baseline: 1, no pyramiding)
  - sizes the position from CURRENT equity (percentage risk, section 18)
  - applies transaction costs to the fill (section 20)
  - simulates the exit bar-by-bar (execution/simulator.py)
  - updates equity strictly in chronological order of trade CLOSES being
    realized before later trades can use the updated equity

This file contains no strategy logic — it only sequences and prices
already-generated setups. That separation is what lets the same setup list
be reused, unmodified, by the portfolio backtest (backtest/portfolio.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backtest.trade import Trade
from execution.costs import CostModel, commission_cost, entry_fill_price, exit_fill_price
from execution.simulator import ExitReason, simulate_exit
from risk.pips import price_diff_to_pips
from risk.position_sizing import quote_to_usd_factor, size_position
from strategy.signals import RejectionReason, SetupOutcome


@dataclass
class RejectionStats:
    n_valid_setups: int = 0
    n_rejected_setups: int = 0
    n_rejected_sl_too_large: int = 0
    n_rejected_ma200_wrong_side: int = 0
    n_rejected_rr_insufficient: int = 0
    n_rejected_zero_risk: int = 0
    n_rejected_no_next_candle: int = 0
    n_skipped_max_open_trades: int = 0
    n_skipped_zero_position_size: int = 0
    n_buy_trades: int = 0
    n_sell_trades: int = 0


@dataclass
class PairBacktestResult:
    pair: str
    trades: list[Trade]
    rejected_setups: list[SetupOutcome]
    stats: RejectionStats
    equity_curve: pd.Series          # indexed by exit timestamp, includes a leading initial-capital point
    final_equity: float


def run_pair_backtest(
    pair: str,
    df: pd.DataFrame,
    cfg: dict,
    setups: list[SetupOutcome],
    initial_capital: float | None = None,
) -> PairBacktestResult:
    pip_size = cfg["pairs"][pair]["pip_size"]
    tc = cfg["transaction_costs"][pair]
    costs = CostModel(
        spread_pips=tc["spread_pips"],
        slippage_pips=tc["slippage_pips"],
        commission_per_lot_round_turn=cfg["commission_per_lot_round_turn"],
        pip_size=pip_size,
    )
    equity = cfg["initial_capital"] if initial_capital is None else initial_capital
    max_open = cfg["max_open_trades_per_pair"]

    stats = RejectionStats()
    trades: list[Trade] = []
    rejected: list[SetupOutcome] = []

    ordered = sorted(setups, key=lambda s: s.confirmation_index)
    open_until_index: int | None = None  # entry_index of the exit bar of the currently open trade
    n_open = 0

    equity_points = [(df["timestamp"].iat[0], equity)]

    for setup in ordered:
        if not setup.accepted:
            stats.n_rejected_setups += 1
            for r in setup.rejection_reasons:
                if r == RejectionReason.SL_TOO_LARGE:
                    stats.n_rejected_sl_too_large += 1
                elif r == RejectionReason.MA200_WRONG_SIDE:
                    stats.n_rejected_ma200_wrong_side += 1
                elif r == RejectionReason.RR_INSUFFICIENT:
                    stats.n_rejected_rr_insufficient += 1
                elif r == RejectionReason.ZERO_RISK:
                    stats.n_rejected_zero_risk += 1
                elif r == RejectionReason.NO_NEXT_CANDLE:
                    stats.n_rejected_no_next_candle += 1
            rejected.append(setup)
            continue

        stats.n_valid_setups += 1

        if n_open >= max_open and open_until_index is not None and setup.entry_index <= open_until_index:
            stats.n_skipped_max_open_trades += 1
            continue

        sizing = size_position(
            account_equity=equity,
            risk_per_trade=cfg["risk_per_trade"],
            sl_distance_pips=setup.sl_pips,
            pair=pair,
            pip_size=pip_size,
            lot_size=cfg["lot_size"],
            lot_step=cfg["lot_step"],
            min_lot=cfg["min_lot"],
            usdjpy_rate=cfg["usdjpy_conversion_rate"],
        )
        if sizing.lots <= 0:
            stats.n_skipped_zero_position_size += 1
            continue

        entry_fill = entry_fill_price(setup.direction, setup.raw_entry, costs)

        exit_result = simulate_exit(
            df=df,
            entry_index=setup.entry_index,
            direction=setup.direction,
            sl=setup.sl,
            tp=setup.tp,
            same_candle_policy=cfg["same_candle_policy"],
        )
        exit_fill = exit_fill_price(setup.direction, exit_result.exit_price_raw, costs)
        commission = commission_cost(sizing.lots, costs)

        sign = 1.0 if setup.direction == "BUY" else -1.0
        fx = quote_to_usd_factor(pair, cfg["usdjpy_conversion_rate"])
        gross_pnl_usd = (exit_fill - entry_fill) * sizing.units * sign * fx
        pnl = gross_pnl_usd - commission
        equity += pnl

        r_multiple = pnl / sizing.risk_amount if sizing.risk_amount > 0 else float("nan")

        trade = Trade(
            pair=pair,
            timestamp=setup.entry_timestamp,
            direction=setup.direction,
            zone_type=setup.zone.zone_type.value,
            zone_high=setup.zone.upper,
            zone_low=setup.zone.lower,
            entry=entry_fill,
            stop_loss=setup.sl,
            take_profit=setup.tp,
            sl_pips=setup.sl_pips,
            tp_pips=setup.tp_pips,
            initial_rr=setup.rr,
            ma200_at_entry=setup.ma200_at_confirmation,
            atr_at_entry=setup.atr_at_confirmation,
            position_size_lots=sizing.lots,
            risk_amount=sizing.risk_amount,
            spread_pips=costs.spread_pips,
            slippage_pips=costs.slippage_pips,
            exit_timestamp=exit_result.exit_timestamp,
            exit_price=exit_fill,
            exit_reason=exit_result.exit_reason.value,
            pnl=pnl,
            r_multiple=r_multiple,
            equity_after=equity,
            holding_bars=exit_result.exit_index - setup.entry_index,
        )
        trades.append(trade)
        equity_points.append((exit_result.exit_timestamp, equity))

        if setup.direction == "BUY":
            stats.n_buy_trades += 1
        else:
            stats.n_sell_trades += 1

        open_until_index = exit_result.exit_index
        n_open = 1  # baseline: max_open_trades_per_pair == 1

    equity_series = pd.Series(
        data=[p[1] for p in equity_points],
        index=pd.DatetimeIndex([p[0] for p in equity_points]),
    )
    equity_series = equity_series[~equity_series.index.duplicated(keep="last")].sort_index()

    return PairBacktestResult(
        pair=pair,
        trades=trades,
        rejected_setups=rejected,
        stats=stats,
        equity_curve=equity_series,
        final_equity=equity,
    )
