"""Pip-size-aware conversions. NEVER assume 0.0001 for every pair — JPY
crosses use 0.01 (section 15 of the spec)."""
from __future__ import annotations


def price_diff_to_pips(price_diff: float, pip_size: float) -> float:
    return abs(price_diff) / pip_size


def pips_to_price(pips: float, pip_size: float) -> float:
    return pips * pip_size
