"""Walk-forward testing (section 33).

TRAIN -> TEST -> TRAIN -> TEST ... windows walked forward across the whole
series. As with out_of_sample.py, this strategy has fixed, non-fitted
parameters, so the "TRAIN" segment of each window is not used to fit
anything — its role here is purely to define where each "TEST" segment
begins, matching the walk-forward structure the spec asks for. Equity
compounds sequentially across TEST windows only (never using a TRAIN
window's price action to trade), which is what "Walk-Forward Performance"
in the final report reflects.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from analysis.metrics import PerformanceMetrics, compute_metrics
from backtest.engine import run_pair_backtest
from backtest.trade import Trade
from strategy.signals import SignalGenerationResult


@dataclass
class WalkForwardWindow:
    train_start_ts: pd.Timestamp
    train_end_ts: pd.Timestamp
    test_start_ts: pd.Timestamp
    test_end_ts: pd.Timestamp
    n_trades: int
    net_pnl: float
    equity_after: float


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    all_trades: list[Trade]
    equity_curve: pd.Series
    metrics: PerformanceMetrics


def run_walk_forward(
    pair: str,
    df: pd.DataFrame,
    cfg: dict,
    signal_result: SignalGenerationResult,
) -> WalkForwardResult:
    wf_cfg = cfg["walk_forward"]
    train_bars, test_bars, step_bars = wf_cfg["train_bars"], wf_cfg["test_bars"], wf_cfg["step_bars"]
    n = len(df)

    equity = cfg["initial_capital"]
    all_trades: list[Trade] = []
    windows: list[WalkForwardWindow] = []
    equity_points = [(df["timestamp"].iat[0], equity)]

    start = 0
    while start + train_bars + test_bars <= n:
        train_start_idx = start
        train_end_idx = start + train_bars
        test_start_idx = train_end_idx
        test_end_idx = min(test_start_idx + test_bars, n - 1)

        train_start_ts = df["timestamp"].iat[train_start_idx]
        train_end_ts = df["timestamp"].iat[train_end_idx]
        test_start_ts = df["timestamp"].iat[test_start_idx]
        test_end_ts = df["timestamp"].iat[test_end_idx]

        window_setups = [
            s for s in signal_result.setups
            if test_start_ts <= s.confirmation_timestamp < test_end_ts
        ]
        result = run_pair_backtest(pair, df, cfg, window_setups, initial_capital=equity)
        net_pnl = result.final_equity - equity
        equity = result.final_equity
        all_trades.extend(result.trades)
        for t in result.trades:
            equity_points.append((t.exit_timestamp, t.equity_after))

        windows.append(
            WalkForwardWindow(
                train_start_ts=train_start_ts,
                train_end_ts=train_end_ts,
                test_start_ts=test_start_ts,
                test_end_ts=test_end_ts,
                n_trades=len(result.trades),
                net_pnl=net_pnl,
                equity_after=equity,
            )
        )
        start += step_bars

    equity_series = pd.Series(
        data=[p[1] for p in equity_points], index=pd.DatetimeIndex([p[0] for p in equity_points])
    )
    equity_series = equity_series[~equity_series.index.duplicated(keep="last")].sort_index()

    metrics = compute_metrics(all_trades, equity_series, cfg["initial_capital"])

    return WalkForwardResult(windows=windows, all_trades=all_trades, equity_curve=equity_series, metrics=metrics)
