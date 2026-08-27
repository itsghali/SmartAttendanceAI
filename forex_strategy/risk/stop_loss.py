"""Structural stop loss (section 13/14).

BUY : SL = demand.lower - ATR * SL_BUFFER_ATR_MULTIPLIER
SELL: SL = supply.upper + ATR * SL_BUFFER_ATR_MULTIPLIER

The SL is always structurally connected to the zone. It is NEVER moved
closer to price to satisfy the max-pip filter — if it is too wide, the trade
is rejected outright (see risk/risk_reward.py `check_max_sl_pips`).
"""
from __future__ import annotations

from zones.lifecycle import Zone, ZoneType


def structural_stop_loss(zone: Zone, atr_at_confirmation: float, sl_buffer_atr_multiplier: float) -> float:
    buffer = atr_at_confirmation * sl_buffer_atr_multiplier
    if zone.zone_type == ZoneType.DEMAND:
        return zone.lower - buffer
    return zone.upper + buffer
