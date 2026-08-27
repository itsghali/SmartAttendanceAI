"""Combined portfolio backtest (section 2 / 28).

Reuses the exact same, already-generated per-pair setup lists (no strategy
logic is duplicated or reinterpreted here) but executes them against ONE
shared equity curve, processed in strict chronological order of entry
across ALL pairs. `max_open_trades_per_pair` is still enforced per pair
(so EUR/USD and GBP/JPY can be open at the same time, but two EUR/USD
trades cannot overlap) — different pairs are not assumed to behave the
same, they simply share a capital base.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.trade import Trade
from execution.costs import CostModel, commission_cost, entry_fill_price, exit_fill_price
from execution.simulator import simulate_exit
from risk.position_sizing import quote_to_usd_factor, size_position
from strategy.signals import SetupOutcome


@dataclass
class PortfolioBacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    final_equity: float


def run_portfolio_backtest(
    cfg: dict,
    dfs: dict[str, pd.DataFrame],
    setups_by_pair: dict[str, list[SetupOutcome]],
) -> PortfolioBacktestResult:
    equity = cfg["initial_capital"]
    all_setups: list[SetupOutcome] = []
    for pair, setups in setups_by_pair.items():
        all_setups.extend(s for s in setups if s.accepted)
    all_setups.sort(key=lambda s: s.entry_timestamp)

    open_until_ts: dict[str, pd.Timestamp] = {}
    trades: list[Trade] = []
    equity_points = []
    first_ts = min(df["timestamp"].iat[0] for df in dfs.values())
    equity_points.append((first_ts, equity))

    for setup in all_setups:
        pair = setup.pair
        if pair in open_until_ts and setup.entry_timestamp <= open_until_ts[pair]:
            continue  # per-pair concurrency limit (baseline: 1 open trade per pair)

        df = dfs[pair]
        pip_size = cfg["pairs"][pair]["pip_size"]
        tc = cfg["transaction_costs"][pair]
        costs = CostModel(
            spread_pips=tc["spread_pips"],
            slippage_pips=tc["slippage_pips"],
            commission_per_lot_round_turn=cfg["commission_per_lot_round_turn"],
            pip_size=pip_size,
        )

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
        pnl = (exit_fill - entry_fill) * sizing.units * sign * fx - commission
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
        open_until_ts[pair] = exit_result.exit_timestamp

    equity_series = pd.Series(
        data=[p[1] for p in equity_points],
        index=pd.DatetimeIndex([p[0] for p in equity_points]),
    )
    equity_series = equity_series[~equity_series.index.duplicated(keep="last")].sort_index()

    return PortfolioBacktestResult(trades=trades, equity_curve=equity_series, final_equity=equity)
