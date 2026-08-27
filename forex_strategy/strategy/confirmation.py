"""Pure, stateless confirmation-candle predicates (section 11/12 of spec).

A confirmation candle for a Demand zone must:
    - close bullish:                 close > open
    - close back above the zone:     close > zone.upper
A confirmation candle for a Supply zone must (mirror image):
    - close bearish:                 close < open
    - close back below the zone:     close < zone.lower

Resolved ambiguity: the spec does not say how many candles after the first
interaction confirmation may occur on. We define the confirmation candle to
be the SAME candle that interacts with the zone (interaction and the close
condition are evaluated on one candle) — this is the simplest deterministic
reading and avoids introducing an unconfigured "confirmation window"
parameter that is not mentioned anywhere in the spec. If a candle interacts
but does not confirm, the zone is simply left ACTIVE/TESTED for future
candles to attempt confirmation.
"""
from __future__ import annotations

from zones.lifecycle import Zone, ZoneType, candle_interacts


def is_bullish(open_: float, close: float) -> bool:
    return close > open_


def is_bearish(open_: float, close: float) -> bool:
    return close < open_


def confirms_demand(open_: float, high: float, low: float, close: float, zone: Zone) -> bool:
    if zone.zone_type != ZoneType.DEMAND:
        return False
    if not candle_interacts(low, high, zone):
        return False
    if not is_bullish(open_, close):
        return False
    return close > zone.upper


def confirms_supply(open_: float, high: float, low: float, close: float, zone: Zone) -> bool:
    if zone.zone_type != ZoneType.SUPPLY:
        return False
    if not candle_interacts(low, high, zone):
        return False
    if not is_bearish(open_, close):
        return False
    return close < zone.lower
