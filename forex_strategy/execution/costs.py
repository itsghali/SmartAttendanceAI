"""Transaction cost model (section 20).

Resolved ambiguity: the full configured spread is charged once, on entry
(the classic "cross the spread to open" cost); slippage is applied on BOTH
entry and exit fills, since it represents execution uncertainty on any
market order, not a bid/ask structure. Commission is a flat, configurable
USD amount per standard lot, charged once per round-turn trade. All three
are configurable per pair / globally in config.yaml and are deliberately
kept OUT of the signal-validity filters (risk/risk_reward.py) so that
"is there a structural edge" and "does it survive costs" can be reported
separately (see backtest/engine.py).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    spread_pips: float
    slippage_pips: float
    commission_per_lot_round_turn: float
    pip_size: float


def entry_fill_price(direction: str, raw_price: float, costs: CostModel) -> float:
    adverse = (costs.spread_pips + costs.slippage_pips) * costs.pip_size
    if direction == "BUY":
        return raw_price + adverse
    return raw_price - adverse


def exit_fill_price(direction: str, raw_price: float, costs: CostModel) -> float:
    adverse = costs.slippage_pips * costs.pip_size
    if direction == "BUY":  # closing a long = selling
        return raw_price - adverse
    return raw_price + adverse  # closing a short = buying


def commission_cost(lots: float, costs: CostModel) -> float:
    return lots * costs.commission_per_lot_round_turn
