"""Static MA200 take profit (section 4).

TP is frozen at the MA200 value that existed at the confirmation candle's
close. It is never recalculated as MA200 subsequently moves.

BUY  is only valid when TP (== MA200 at entry) > entry price.
SELL is only valid when TP (== MA200 at entry) < entry price.
"""
from __future__ import annotations


def take_profit_from_ma200(ma200_at_confirmation: float) -> float:
    return ma200_at_confirmation


def tp_direction_valid(direction: str, tp: float, entry_price: float) -> bool:
    if direction == "BUY":
        return tp > entry_price
    if direction == "SELL":
        return tp < entry_price
    raise ValueError(f"unknown direction {direction!r}")
