"""Percentage-risk position sizing with correct per-pair pip value
(section 18).

Pip value per standard lot (100,000 units), in the pair's quote currency:
    pip_value_quote = pip_size * lot_size

The account is assumed to be denominated in USD. For quote currencies other
than USD (only GBP/JPY among the four traded pairs), the quote-currency pip
value is converted to USD using a configurable reference rate
(`usdjpy_conversion_rate`) — see README "Resolved Ambiguities" for why this
approximation is necessary (we do not ingest a USD/JPY series) and how to
replace it with a live conversion if one becomes available.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PositionSizeResult:
    lots: float
    units: float
    pip_value_usd_per_lot: float
    risk_amount: float


def quote_to_usd_factor(pair: str, usdjpy_rate: float) -> float:
    """Multiply any quote-currency amount (P&L, pip value, ...) by this to
    get USD. 1.0 for pairs already quoted in USD; 1/usdjpy_rate for JPY
    crosses. MUST be applied consistently everywhere quote-currency money
    flows into the (USD) account equity — both for position sizing (below)
    and for realized trade P&L (execution/costs.py callers in
    backtest/engine.py and backtest/portfolio.py) — otherwise a JPY P&L
    gets added to USD equity unconverted, silently inflating results by
    ~100x for GBP/JPY."""
    if pair.endswith("JPY"):
        return 1.0 / usdjpy_rate
    return 1.0


def pip_value_usd_per_lot(pair: str, pip_size: float, lot_size: float, usdjpy_rate: float) -> float:
    pip_value_quote = pip_size * lot_size
    return pip_value_quote * quote_to_usd_factor(pair, usdjpy_rate)


def size_position(
    account_equity: float,
    risk_per_trade: float,
    sl_distance_pips: float,
    pair: str,
    pip_size: float,
    lot_size: float,
    lot_step: float,
    min_lot: float,
    usdjpy_rate: float,
) -> PositionSizeResult:
    if sl_distance_pips <= 0:
        raise ValueError("sl_distance_pips must be positive")

    risk_amount = account_equity * risk_per_trade
    pv = pip_value_usd_per_lot(pair, pip_size, lot_size, usdjpy_rate)

    raw_lots = risk_amount / (sl_distance_pips * pv)
    # Round DOWN to the broker's lot step — never risk more than the
    # configured percentage by rounding up.
    lots = math.floor(raw_lots / lot_step) * lot_step
    lots = max(lots, 0.0)
    if lots < min_lot:
        lots = 0.0  # position too small to open at all

    units = lots * lot_size
    return PositionSizeResult(
        lots=lots,
        units=units,
        pip_value_usd_per_lot=pv,
        risk_amount=risk_amount,
    )
