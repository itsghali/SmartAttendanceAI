"""Research-Grade Forex Backtesting System — CLI entry point.

Runs the full pipeline in the order specified in the README / spec section
41:
    load -> validate -> indicators -> swings -> zones -> lifecycle ->
    retest -> confirmation -> structural SL -> max-SL filter -> MA200 TP ->
    RR filter -> position sizing -> transaction costs -> execution ->
    backtest -> metrics -> visualization -> sensitivity -> out-of-sample ->
    walk-forward -> final report

If data/raw/<PAIR>_M30.csv does not exist for a configured pair, a
reproducible SYNTHETIC dataset is generated in its place (see
data/synthetic.py) purely so the system is runnable end to end without a
real data vendor. Replace those files with real broker data for actual
research.
"""
from __future__ import annotations

import os

import pandas as pd

from analysis.metrics import compute_metrics
from analysis.pair_comparison import build_comparison_table
from analysis.report import generate_report
from analysis.trade_log import save_rejected_setups_csv, save_trades_csv
from backtest.engine import run_pair_backtest
from backtest.out_of_sample import run_in_out_sample
from backtest.portfolio import run_portfolio_backtest
from backtest.sensitivity import run_sensitivity_grid
from backtest.walk_forward import run_walk_forward
from config_loader import load_config, with_overrides
from data.loader import load_csv
from data.synthetic import PAIR_SEED, generate_synthetic_m30
from data.validator import validate
from strategy.signals import generate_signals
from visualization.equity_curves import plot_combined_equity, plot_equity_and_drawdown
from visualization.trade_charts import plot_trade_chart

BASE_DIR = os.path.dirname(__file__)
OUT_DIR = os.path.join(BASE_DIR, "outputs")


def _ensure_dirs():
    for sub in ("trade_logs", "reports", "charts", "equity_curves"):
        os.makedirs(os.path.join(OUT_DIR, sub), exist_ok=True)


def load_pair_data(pair: str, cfg: dict) -> tuple[pd.DataFrame, bool]:
    path = os.path.join(BASE_DIR, cfg["pairs"][pair]["file"])
    is_synthetic = False
    if not os.path.exists(path):
        is_synthetic = True
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df = generate_synthetic_m30(
            pair=pair, pip_size=cfg["pairs"][pair]["pip_size"], seed=PAIR_SEED.get(pair, 42)
        )
        df.to_csv(path, index=False)
    df = load_csv(path)
    df, report = validate(df, pair=pair)
    if report.warnings:
        for w in report.warnings:
            print(f"[{pair}] data warning: {w}")
    return df, is_synthetic


def main():
    cfg = load_config()
    pairs = list(cfg["pairs"].keys())
    _ensure_dirs()

    dfs: dict[str, pd.DataFrame] = {}
    synthetic_flags = {}
    for pair in pairs:
        df, is_synth = load_pair_data(pair, cfg)
        dfs[pair] = df
        synthetic_flags[pair] = is_synth
        print(f"[{pair}] loaded {len(df)} candles "
              f"({df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]})"
              f"{' [SYNTHETIC]' if is_synth else ''}")

    # ---- baseline run (config.yaml as-is) ----------------------------------
    signal_results = {}
    pair_results = {}
    metrics_by_pair = {}
    for pair in pairs:
        sig = generate_signals(pair, dfs[pair], cfg)
        signal_results[pair] = sig
        res = run_pair_backtest(pair, dfs[pair], cfg, sig.setups)
        pair_results[pair] = res
        metrics_by_pair[pair] = compute_metrics(res.trades, res.equity_curve, cfg["initial_capital"])

        save_trades_csv(res.trades, os.path.join(OUT_DIR, "trade_logs", f"{pair}_trades.csv"))
        save_rejected_setups_csv(res.rejected_setups, os.path.join(OUT_DIR, "trade_logs", f"{pair}_rejected.csv"))
        plot_equity_and_drawdown(res.equity_curve, pair, os.path.join(OUT_DIR, "equity_curves", f"{pair}_equity.png"))

        print(f"[{pair}] trades={len(res.trades)} "
              f"win_rate={metrics_by_pair[pair].win_rate_pct:.1f}% "
              f"net_return={metrics_by_pair[pair].net_return_pct:.1f}% "
              f"max_dd={metrics_by_pair[pair].max_drawdown_pct:.1f}%")

    comparison_table = build_comparison_table(metrics_by_pair)

    setups_by_pair = {pair: signal_results[pair].setups for pair in pairs}
    portfolio = run_portfolio_backtest(cfg, dfs, setups_by_pair)
    portfolio_metrics = compute_metrics(portfolio.trades, portfolio.equity_curve, cfg["initial_capital"])
    save_trades_csv(portfolio.trades, os.path.join(OUT_DIR, "trade_logs", "PORTFOLIO_trades.csv"))
    plot_equity_and_drawdown(portfolio.equity_curve, "Portfolio", os.path.join(OUT_DIR, "equity_curves", "PORTFOLIO_equity.png"))

    combined_curves = {pair: pair_results[pair].equity_curve for pair in pairs}
    combined_curves["PORTFOLIO"] = portfolio.equity_curve
    plot_combined_equity(combined_curves, os.path.join(OUT_DIR, "equity_curves", "ALL_equity.png"))

    print(f"[PORTFOLIO] trades={len(portfolio.trades)} net_return={portfolio_metrics.net_return_pct:.1f}% "
          f"max_dd={portfolio_metrics.max_drawdown_pct:.1f}% sharpe={portfolio_metrics.sharpe_ratio:.2f}")

    # ---- 15 vs 20 pip SL comparison (section 31) ---------------------------
    sl_rows = []
    for max_sl in cfg["sensitivity"]["max_sl_pips"]:
        setups_by_pair_sl = {
            pair: generate_signals(pair, dfs[pair], cfg, max_sl_pips=max_sl).setups for pair in pairs
        }
        port = run_portfolio_backtest(cfg, dfs, setups_by_pair_sl)
        m = compute_metrics(port.trades, port.equity_curve, cfg["initial_capital"])
        sl_rows.append({
            "max_sl_pips": max_sl, "n_trades": m.n_trades, "win_rate_pct": round(m.win_rate_pct, 2),
            "profit_factor": round(m.profit_factor, 2) if m.profit_factor != float("inf") else float("inf"),
            "expectancy": round(m.expectancy, 2), "net_return_pct": round(m.net_return_pct, 2),
            "max_drawdown_pct": round(m.max_drawdown_pct, 2), "sharpe_ratio": round(m.sharpe_ratio, 2),
            "avg_r_multiple": round(m.avg_r_multiple, 3), "max_losing_streak": m.max_losing_streak,
        })
    sl_comparison_table = pd.DataFrame(sl_rows)

    # ---- transaction cost sensitivity (section 20) -------------------------
    cost_rows = []
    for mult in [0.0, 1.0, 1.5, 2.0]:
        run_cfg = with_overrides(cfg, {
            "transaction_costs": {
                pair: {
                    "spread_pips": cfg["transaction_costs"][pair]["spread_pips"] * mult,
                    "slippage_pips": cfg["transaction_costs"][pair]["slippage_pips"] * mult,
                }
                for pair in pairs
            }
        })
        setups_cost = {pair: signal_results[pair].setups for pair in pairs}
        port = run_portfolio_backtest(run_cfg, dfs, setups_cost)
        m = compute_metrics(port.trades, port.equity_curve, run_cfg["initial_capital"])
        cost_rows.append({
            "cost_multiplier": mult, "n_trades": m.n_trades, "net_return_pct": round(m.net_return_pct, 2),
            "expectancy": round(m.expectancy, 2), "profit_factor": round(m.profit_factor, 2) if m.profit_factor != float("inf") else float("inf"),
            "max_drawdown_pct": round(m.max_drawdown_pct, 2),
        })
    cost_sensitivity_table = pd.DataFrame(cost_rows)

    # ---- parameter sensitivity grids (section 32) --------------------------
    sens_cfg = cfg["sensitivity"]
    sensitivity_tables = {
        "max_sl_pips x min_rr": run_sensitivity_grid(cfg, dfs, {
            "max_sl_pips": sens_cfg["max_sl_pips"], "min_rr": sens_cfg["min_rr"],
        }),
        "displacement_min_atr_multiplier": run_sensitivity_grid(cfg, dfs, {
            "displacement_min_atr_multiplier": sens_cfg["displacement_min_atr_multiplier"],
        }),
        "swing_lookback": run_sensitivity_grid(cfg, dfs, {
            "swing_lookback": sens_cfg["swing_lookback"],
        }),
        "sl_buffer_atr_multiplier": run_sensitivity_grid(cfg, dfs, {
            "sl_buffer_atr_multiplier": sens_cfg["sl_buffer_atr_multiplier"],
        }),
    }

    # ---- out-of-sample + walk-forward (section 33) -------------------------
    out_of_sample_results = {pair: run_in_out_sample(pair, dfs[pair], cfg, signal_results[pair]) for pair in pairs}
    walk_forward_results = {pair: run_walk_forward(pair, dfs[pair], cfg, signal_results[pair]) for pair in pairs}

    # ---- trade charts (section 30): winners, losers, rejected --------------
    for pair in pairs:
        trades = pair_results[pair].trades
        ma200 = signal_results[pair].ma200
        df = dfs[pair]
        winners = [t for t in trades if t.pnl and t.pnl > 0][:2]
        losers = [t for t in trades if t.pnl and t.pnl <= 0][:2]
        for label, group in (("winner", winners), ("loser", losers)):
            for k, t in enumerate(group):
                idx = df.index[df["timestamp"] == t.timestamp]
                center = int(idx[0]) if len(idx) else 0
                exit_idx_arr = df.index[df["timestamp"] == t.exit_timestamp]
                exit_idx = int(exit_idx_arr[0]) if len(exit_idx_arr) else None
                plot_trade_chart(
                    df, ma200, center, t.zone_high, t.zone_low, t.zone_type,
                    t.entry, t.stop_loss, t.take_profit, exit_idx, t.exit_price, center,
                    f"{pair} {label} #{k+1} ({t.direction}, {t.exit_reason})",
                    os.path.join(OUT_DIR, "charts", f"{pair}_{label}_{k+1}.png"),
                )

        rejected_sl_too_large = [
            s for s in pair_results[pair].rejected_setups
            if any(r.value == "SL_TOO_LARGE" for r in s.rejection_reasons)
        ][:2]
        for k, s in enumerate(rejected_sl_too_large):
            plot_trade_chart(
                df, ma200, s.confirmation_index, s.zone.upper, s.zone.lower, s.zone.zone_type.value,
                s.raw_entry, s.sl, s.tp, None, None, s.entry_index,
                f"{pair} REJECTED (SL too large) #{k+1} ({s.direction})",
                os.path.join(OUT_DIR, "charts", f"{pair}_rejected_sl_{k+1}.png"),
            )

    # ---- final report --------------------------------------------------------
    zone_stats = {
        pair: {
            "n_demand_zones": signal_results[pair].n_demand_zones,
            "n_supply_zones": signal_results[pair].n_supply_zones,
            "n_retests": signal_results[pair].n_retests,
        }
        for pair in pairs
    }
    rejection_stats = {pair: pair_results[pair].stats for pair in pairs}

    ctx = {
        "pairs": pairs,
        "synthetic": any(synthetic_flags.values()),
        "portfolio_metrics": portfolio_metrics,
        "comparison_table": comparison_table,
        "sl_comparison_table": sl_comparison_table,
        "cost_sensitivity_table": cost_sensitivity_table,
        "sensitivity_tables": sensitivity_tables,
        "out_of_sample": out_of_sample_results,
        "walk_forward": walk_forward_results,
        "zone_stats": zone_stats,
        "rejection_stats": rejection_stats,
    }
    report_md = generate_report(ctx)
    report_path = os.path.join(OUT_DIR, "reports", "research_report.md")
    with open(report_path, "w") as f:
        f.write(report_md)
    print(f"\nFinal report written to {report_path}")


if __name__ == "__main__":
    main()
