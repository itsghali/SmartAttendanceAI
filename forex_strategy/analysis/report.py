"""Automated research report generator (section 39).

Takes the already-computed results from main.py and renders one Markdown
document that directly answers every question the spec asks for. This
module does no computation of its own beyond simple comparisons/formatting
— every number it prints was produced by the engine, metrics, sensitivity,
out-of-sample, or walk-forward modules.
"""
from __future__ import annotations

from analysis.metrics import PerformanceMetrics


def _fmt(x, decimals=2):
    if x is None:
        return "n/a"
    if isinstance(x, float) and (x != x):  # NaN
        return "n/a"
    if x == float("inf"):
        return "inf"
    return f"{x:,.{decimals}f}"


def _metrics_block(m: PerformanceMetrics) -> str:
    return (
        f"- Net return: {_fmt(m.net_return_pct)}%  |  CAGR: {_fmt(m.cagr_pct)}%\n"
        f"- Max drawdown: {_fmt(m.max_drawdown_pct)}%  |  Sharpe: {_fmt(m.sharpe_ratio)}  |  "
        f"Sortino: {_fmt(m.sortino_ratio)}  |  Calmar: {_fmt(m.calmar_ratio)}\n"
        f"- Trades: {m.n_trades}  |  Win rate: {_fmt(m.win_rate_pct)}%  |  "
        f"Profit factor: {_fmt(m.profit_factor)}  |  Expectancy: {_fmt(m.expectancy)}  |  Avg R: {_fmt(m.avg_r_multiple, 3)}\n"
        f"- Best / worst trade: {_fmt(m.best_trade)} / {_fmt(m.worst_trade)}\n"
        f"- Max winning streak: {m.max_winning_streak}  |  Max losing streak: {m.max_losing_streak}\n"
        f"- Avg holding: {_fmt(m.avg_holding_bars, 1)} bars ({_fmt(m.avg_holding_bars * 0.5, 1)}h)  |  "
        f"Median holding: {_fmt(m.median_holding_bars, 1)} bars\n"
    )


def generate_report(ctx: dict) -> str:
    lines = []
    a = lines.append

    a("# Research-Grade Forex Backtesting — Results Report\n")
    a(f"Generated for pairs: {', '.join(ctx['pairs'])}  |  Timeframe: M30\n")
    a("**This run used SYNTHETIC data unless real CSVs were supplied — see data/synthetic.py "
      "and README. Treat all numbers below as a pipeline demonstration unless real market data "
      "was used.**\n" if ctx.get("synthetic", True) else "")

    a("\n## 1. Strategy Performance (baseline config)\n")
    portfolio_m: PerformanceMetrics = ctx["portfolio_metrics"]
    a("### Combined portfolio\n")
    a(_metrics_block(portfolio_m))
    positive = portfolio_m.expectancy > 0
    a(f"\n**Is historical expectancy positive?** {'YES' if positive else 'NO'} "
      f"(expectancy = {_fmt(portfolio_m.expectancy)} USD/trade).\n")

    a("\n## 2. Pair Comparison\n")
    a(ctx["comparison_table"].to_markdown(index=False))
    a("\n")
    best_pair = ctx["comparison_table"].sort_values("Expectancy", ascending=False).iloc[0]["Pair"]
    worst_pair = ctx["comparison_table"].sort_values("Expectancy", ascending=True).iloc[0]["Pair"]
    a(f"\n**Best pair (by expectancy):** {best_pair}. **Worst pair:** {worst_pair}.\n")
    trade_counts = ctx["comparison_table"].set_index("Pair")["Trades"]
    total_trades = trade_counts.sum()
    if total_trades > 0:
        concentration = (trade_counts.max() / total_trades) * 100
        a(f"**Trade concentration:** the busiest pair accounts for {_fmt(concentration)}% of all trades "
          f"across the four pairs — {'performance IS concentrated in one pair, interpret with caution' if concentration > 50 else 'trade count is reasonably spread across pairs'}.\n")

    a("\n## 3. SL Analysis: 15 pips vs 20 pips\n")
    sl_cmp = ctx["sl_comparison_table"]
    a(sl_cmp.to_markdown(index=False))
    a("\n")
    row15 = sl_cmp[sl_cmp["max_sl_pips"] == 15].iloc[0]
    row20 = sl_cmp[sl_cmp["max_sl_pips"] == 20].iloc[0]
    a(f"\n- Trades available at 15 pips: {int(row15['n_trades'])}; at 20 pips: {int(row20['n_trades'])} "
      f"({int(row20['n_trades']) - int(row15['n_trades'])} additional trades become available).\n")
    better = "20-pip" if row20["expectancy"] > row15["expectancy"] else "15-pip"
    a(f"- By expectancy, the **{better}** limit performs better in this run "
      f"({_fmt(row15['expectancy'])} vs {_fmt(row20['expectancy'])} USD/trade). "
      "This is a single historical sample — do not treat this as proof either limit dominates.\n")

    a("\n## 4. Robustness\n")

    a("\n### 4a. Transaction cost sensitivity\n")
    a(ctx["cost_sensitivity_table"].to_markdown(index=False))
    a("\n")

    a("\n### 4b. Parameter sensitivity\n")
    for name, table in ctx["sensitivity_tables"].items():
        a(f"\n**{name}**\n\n")
        a(table.to_markdown(index=False))
        a("\n")
    a(
        "\nFlag for overfitting per section 34: look for isolated spikes in the tables above — "
        "a single narrow combination performing far better than every neighboring combination is "
        "a red flag, not a discovery.\n"
    )

    a("\n### 4c. Out-of-sample\n")
    for pair, res in ctx["out_of_sample"].items():
        a(f"\n**{pair}** (in-sample / out-of-sample split at {res.cutoff_timestamp})\n\n")
        a("In-sample:\n\n")
        a(_metrics_block(res.in_sample_metrics))
        a("\nOut-of-sample:\n\n")
        a(_metrics_block(res.out_sample_metrics))
        degraded = res.out_sample_metrics.expectancy < res.in_sample_metrics.expectancy
        a(f"\nOut-of-sample expectancy is {'LOWER' if degraded else 'similar or higher'} than in-sample "
          f"({_fmt(res.out_sample_metrics.expectancy)} vs {_fmt(res.in_sample_metrics.expectancy)}).\n")

    a("\n### 4d. Walk-forward\n")
    for pair, res in ctx["walk_forward"].items():
        a(f"\n**{pair}** — {len(res.windows)} walk-forward window(s)\n\n")
        a(_metrics_block(res.metrics))
        n_positive_windows = sum(1 for w in res.windows if w.net_pnl > 0)
        a(f"\n{n_positive_windows}/{len(res.windows)} windows were net profitable.\n")

    a("\n## 5. Strategy-Specific Statistics\n")
    for pair, stats in ctx["zone_stats"].items():
        a(f"\n**{pair}**: {stats['n_demand_zones']} demand zones, {stats['n_supply_zones']} supply zones, "
          f"{stats['n_retests']} retests detected.\n")
    for pair, rs in ctx["rejection_stats"].items():
        a(
            f"\n**{pair}** setups: {rs.n_valid_setups} valid, {rs.n_rejected_setups} rejected "
            f"(SL too large: {rs.n_rejected_sl_too_large}, MA200 wrong side: {rs.n_rejected_ma200_wrong_side}, "
            f"RR insufficient: {rs.n_rejected_rr_insufficient}). "
            f"BUY trades: {rs.n_buy_trades}, SELL trades: {rs.n_sell_trades}.\n"
        )

    a("\n## 6. Critical Research Principle\n")
    a(
        "This report intentionally evaluates the FULL risk/return profile (drawdown, Sharpe, Sortino, "
        "Calmar, streaks) alongside raw return, and separately reports in-sample vs out-of-sample and "
        "walk-forward performance, because net profit alone is not evidence of edge. A historical "
        "backtest — on synthetic OR real data — never proves future profitability; it only provides "
        "evidence for or against a historical edge under the stated, fixed, non-optimized rules.\n"
    )

    return "\n".join(lines)
