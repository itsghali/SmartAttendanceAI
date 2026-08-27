"""Annotated trade charts for manual rule verification (section 30).

Draws plain OHLC candles (no external plotting dependency beyond
matplotlib) with the Supply/Demand zone, MA200, entry, SL, TP and exit
overlaid, for a window around the trade/setup. Used for winners, losers,
AND rejected setups (including SL > max) — the point is auditability, not
a highlight reel.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle


def _draw_candles(ax, df: pd.DataFrame):
    for pos, (_, row) in enumerate(df.iterrows()):
        color = "#2ea043" if row["close"] >= row["open"] else "#da3633"
        ax.plot([pos, pos], [row["low"], row["high"]], color=color, linewidth=1)
        body_low = min(row["open"], row["close"])
        body_high = max(row["open"], row["close"])
        ax.add_patch(Rectangle((pos - 0.3, body_low), 0.6, max(body_high - body_low, 1e-9), color=color))


def plot_trade_chart(
    df: pd.DataFrame,
    ma200: pd.Series,
    center_index: int,
    zone_upper: float,
    zone_lower: float,
    zone_type: str,
    entry: float | None,
    sl: float | None,
    tp: float | None,
    exit_index: int | None,
    exit_price: float | None,
    entry_index: int | None,
    title: str,
    out_path: str,
    window: int = 60,
):
    lo = max(center_index - window, 0)
    hi = min(center_index + window, len(df) - 1)
    view = df.iloc[lo:hi + 1].reset_index(drop=True)
    x_offset = lo

    fig, ax = plt.subplots(figsize=(12, 6))
    _draw_candles(ax, view)

    ma_view = ma200.iloc[lo:hi + 1].reset_index(drop=True)
    ax.plot(range(len(view)), ma_view.values, color="#8250df", linewidth=1.3, label="MA200")

    zone_color = "#2ea043" if zone_type == "DEMAND" else "#da3633"
    ax.axhspan(zone_lower, zone_upper, color=zone_color, alpha=0.15, label=f"{zone_type} zone")

    if entry is not None and entry_index is not None:
        ax.axhline(entry, color="#1f6feb", linestyle="--", linewidth=1, label="Entry")
        ax.axvline(entry_index - x_offset, color="#1f6feb", linestyle=":", linewidth=0.8)
    if sl is not None:
        ax.axhline(sl, color="#da3633", linestyle="--", linewidth=1, label="SL")
    if tp is not None:
        ax.axhline(tp, color="#2ea043", linestyle="--", linewidth=1, label="TP")
    if exit_index is not None and exit_price is not None:
        ax.scatter([exit_index - x_offset], [exit_price], color="black", zorder=5, label="Exit")

    ax.set_title(title)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
