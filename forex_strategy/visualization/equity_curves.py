"""Equity and drawdown curve plots (section 29)."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot_equity_and_drawdown(equity_curve: pd.Series, title: str, out_path: str) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})

    ax1.plot(equity_curve.index, equity_curve.values, color="#1f6feb", linewidth=1.4)
    ax1.set_title(f"{title} — Equity Curve")
    ax1.set_ylabel("Equity (USD)")
    ax1.grid(alpha=0.3)

    running_max = equity_curve.cummax()
    drawdown_pct = (equity_curve - running_max) / running_max.replace(0, pd.NA) * 100
    ax2.fill_between(equity_curve.index, drawdown_pct.astype(float).fillna(0), 0, color="#da3633", alpha=0.5)
    ax2.set_title("Drawdown %")
    ax2.set_ylabel("Drawdown %")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def plot_combined_equity(curves: dict[str, pd.Series], out_path: str) -> None:
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, curve in curves.items():
        ax.plot(curve.index, curve.values, label=name, linewidth=1.2)
    ax.set_title("Equity Curves — All Pairs + Portfolio")
    ax.set_ylabel("Equity (USD)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
