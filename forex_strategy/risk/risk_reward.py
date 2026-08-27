"""Risk/reward and hard stop-loss filters (sections 14 & 16).

Both filters are evaluated on the theoretical (cost-free) fill price — the
next candle's open — because that is the price the entry rule mechanically
commits to. Transaction costs are applied later, only to the executed P&L
(see execution/costs.py); they never change whether a setup was valid. This
keeps "is there a structural edge" (this module) orthogonal to "does the
edge survive realistic costs" (the execution layer), which is exactly the
sensitivity split section 20 of the spec asks for.
"""
from __future__ import annotations

from dataclasses import dataclass


def compute_risk_reward(entry: float, sl: float, tp: float) -> tuple[float, float, float]:
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else float("nan")
    return risk, reward, rr


def check_max_sl_pips(sl_distance_pips: float, max_sl_pips: float) -> bool:
    return sl_distance_pips <= max_sl_pips


def check_min_rr(rr: float, min_rr: float) -> bool:
    return rr >= min_rr if rr == rr else False  # rr != rr means NaN
