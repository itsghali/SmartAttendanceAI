"""Parameter sensitivity grids (section 32/34).

Runs the full, unmodified pipeline (signal generation -> portfolio
backtest) once per point in a parameter grid. The objective is to see
whether performance is robust across nearby parameter values, not to find
the single best combination — the caller should look at the whole table /
heatmap, not just its maximum.
"""
from __future__ import annotations

import itertools

import pandas as pd

from analysis.metrics import compute_metrics
from backtest.portfolio import run_portfolio_backtest
from config_loader import with_overrides
from strategy.signals import generate_signals


def run_sensitivity_grid(cfg: dict, dfs: dict[str, pd.DataFrame], param_grid: dict[str, list]) -> pd.DataFrame:
    keys = list(param_grid.keys())
    rows = []

    for combo in itertools.product(*param_grid.values()):
        overrides = dict(zip(keys, combo))
        run_cfg = with_overrides(cfg, overrides)

        setups_by_pair = {pair: generate_signals(pair, df, run_cfg).setups for pair, df in dfs.items()}
        portfolio = run_portfolio_backtest(run_cfg, dfs, setups_by_pair)
        metrics = compute_metrics(portfolio.trades, portfolio.equity_curve, run_cfg["initial_capital"])

        row = dict(overrides)
        row.update(
            {
                "n_trades": metrics.n_trades,
                "win_rate_pct": round(metrics.win_rate_pct, 2),
                "profit_factor": round(metrics.profit_factor, 2) if metrics.profit_factor != float("inf") else float("inf"),
                "expectancy": round(metrics.expectancy, 2),
                "net_return_pct": round(metrics.net_return_pct, 2),
                "max_drawdown_pct": round(metrics.max_drawdown_pct, 2),
                "sharpe_ratio": round(metrics.sharpe_ratio, 2),
                "avg_r_multiple": round(metrics.avg_r_multiple, 3),
            }
        )
        rows.append(row)

    return pd.DataFrame(rows)
