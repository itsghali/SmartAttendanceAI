"""Pair comparison table (section 28)."""
from __future__ import annotations

import pandas as pd

from analysis.metrics import PerformanceMetrics


def build_comparison_table(metrics_by_pair: dict[str, PerformanceMetrics]) -> pd.DataFrame:
    rows = []
    for pair, m in metrics_by_pair.items():
        rows.append(
            {
                "Pair": pair,
                "Trades": m.n_trades,
                "Win Rate %": round(m.win_rate_pct, 2),
                "Profit Factor": round(m.profit_factor, 2) if m.profit_factor != float("inf") else "inf",
                "Expectancy": round(m.expectancy, 2),
                "Net Return %": round(m.net_return_pct, 2),
                "Max DD %": round(m.max_drawdown_pct, 2),
                "Sharpe": round(m.sharpe_ratio, 2),
                "Avg R": round(m.avg_r_multiple, 3),
            }
        )
    return pd.DataFrame(rows)
