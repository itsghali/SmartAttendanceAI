"""In-sample / out-of-sample split (section 33).

The strategy has no data-fitted parameters (config.yaml is fixed a priori,
by design — see README "Critical Research Principle"), so there is nothing
to "train". What this split tests is simpler but still meaningful: does the
SAME fixed rule set behave consistently on the earlier vs. the later part
of history, or is its apparent edge concentrated in one sub-period? Signals
are generated ONCE over the full, causally-correct series (no look-ahead is
introduced by this, since detection at any index i already only used data
up to i); only the resulting setups are partitioned by confirmation time.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from analysis.metrics import PerformanceMetrics, compute_metrics
from backtest.engine import PairBacktestResult, run_pair_backtest
from strategy.signals import SignalGenerationResult


@dataclass
class InOutSampleResult:
    cutoff_timestamp: pd.Timestamp
    in_sample_result: PairBacktestResult
    out_sample_result: PairBacktestResult
    in_sample_metrics: PerformanceMetrics
    out_sample_metrics: PerformanceMetrics


def run_in_out_sample(
    pair: str,
    df: pd.DataFrame,
    cfg: dict,
    signal_result: SignalGenerationResult,
) -> InOutSampleResult:
    cutoff_idx = int(len(df) * cfg["in_sample_fraction"])
    cutoff_idx = min(max(cutoff_idx, 0), len(df) - 1)
    cutoff_ts = df["timestamp"].iat[cutoff_idx]

    in_setups = [s for s in signal_result.setups if s.confirmation_timestamp < cutoff_ts]
    out_setups = [s for s in signal_result.setups if s.confirmation_timestamp >= cutoff_ts]

    in_result = run_pair_backtest(pair, df, cfg, in_setups)
    out_result = run_pair_backtest(pair, df, cfg, out_setups)

    in_metrics = compute_metrics(in_result.trades, in_result.equity_curve, cfg["initial_capital"])
    out_metrics = compute_metrics(out_result.trades, out_result.equity_curve, cfg["initial_capital"])

    return InOutSampleResult(
        cutoff_timestamp=cutoff_ts,
        in_sample_result=in_result,
        out_sample_result=out_result,
        in_sample_metrics=in_metrics,
        out_sample_metrics=out_metrics,
    )
