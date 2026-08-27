"""Zone data model and lifecycle state machine.

State transitions (one-directional, never reversed):

    CREATED -> ACTIVE -> TESTED -> INVALIDATED
                      \\-> EXPIRED        (only reachable from ACTIVE, i.e.
                                           before the zone is ever tested)
                       -> TESTED -> INVALIDATED (a TESTED zone can still be
                                           invalidated by a later close)

A zone that reaches INVALIDATED or EXPIRED is dead: it can never again
produce an interaction, a confirmation, or a trade signal. CREATED and
ACTIVE are collapsed in practice — a zone becomes tradeable (ACTIVE) the
candle immediately after the displacement candle that created it, since the
displacement candle's own close is what confirms the zone and cannot also be
used to retest it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ZoneState(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    TESTED = "TESTED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class ZoneType(str, Enum):
    DEMAND = "DEMAND"
    SUPPLY = "SUPPLY"


@dataclass
class Zone:
    zone_id: int
    zone_type: ZoneType
    upper: float                 # upper boundary (highest high of the base)
    lower: float                 # lower boundary (lowest low of the base)
    base_start_index: int
    base_end_index: int
    displacement_index: int      # candle that created the zone
    created_index: int           # == displacement_index
    atr_at_creation: float
    state: ZoneState = ZoneState.ACTIVE
    retest_count: int = 0
    invalidated_index: int | None = None
    expired_index: int | None = None
    tested_indices: list[int] = field(default_factory=list)

    def is_tradeable(self) -> bool:
        return self.state in (ZoneState.ACTIVE, ZoneState.TESTED)

    def is_dead(self) -> bool:
        return self.state in (ZoneState.INVALIDATED, ZoneState.EXPIRED)


def candle_interacts_with_demand(candle_low: float, candle_high: float, zone: Zone) -> bool:
    """candle.low <= demand_high AND candle.high >= demand_low"""
    return candle_low <= zone.upper and candle_high >= zone.lower


def candle_interacts_with_supply(candle_low: float, candle_high: float, zone: Zone) -> bool:
    """candle.high >= supply_low AND candle.low <= supply_high"""
    return candle_high >= zone.lower and candle_low <= zone.upper


def candle_interacts(candle_low: float, candle_high: float, zone: Zone) -> bool:
    if zone.zone_type == ZoneType.DEMAND:
        return candle_interacts_with_demand(candle_low, candle_high, zone)
    return candle_interacts_with_supply(candle_low, candle_high, zone)


def is_invalidated(zone: Zone, candle_close: float, atr_now: float, buffer_mult: float) -> bool:
    """Demand invalid if close < lower - ATR*buffer. Supply invalid if
    close > upper + ATR*buffer. `atr_now` is the ATR of the candle being
    evaluated (i.e., information available at that candle's close only)."""
    buffer = atr_now * buffer_mult
    if zone.zone_type == ZoneType.DEMAND:
        return candle_close < (zone.lower - buffer)
    return candle_close > (zone.upper + buffer)
