"""Supply & Demand zone detection: Base + Displacement + Structure Break.

Mathematical specification (see README section "Mathematical Specification
of the Supply/Demand Algorithm" for the full derivation and the ambiguities
resolved along the way):

1. BASE CANDLE: candle j is a "base candle" iff its range is below-average:
       (high[j] - low[j]) < ATR[j]
   This is the deterministic, ATR-relative stand-in for "consolidation" —
   the spec explicitly forbids subjective terms like "clean" or "tight", so
   we anchor "quiet" to the same ATR yardstick used for displacement.

2. BASE: immediately before a candidate displacement candle at index i, walk
   backwards from i-1 collecting a maximal contiguous run of base candles.
   If that run is empty (i-1 is not a base candle), there is no base and no
   zone can be created from displacement at i. If the run is longer than
   BASE_MAX_CANDLES, only the BASE_MAX_CANDLES candles closest to i are used
   (a documented, deterministic truncation — the base must be "small").

3. DISPLACEMENT at candle i (bullish, for Demand):
       close[i] > open[i]                                   (bullish candle)
       (high[i] - low[i]) >= ATR[i] * DISPLACEMENT_MIN_ATR_MULTIPLIER
   Bearish, for Supply, is the mirror image.

4. STRUCTURE BREAK: the displacement candle's close must break a previously
   CONFIRMED swing point (see zones/swings.py for the no-look-ahead
   confirmation rule):
       Demand: close[i] > price of the most recently confirmed swing high
               as of index i.
       Supply: close[i] < price of the most recently confirmed swing low
               as of index i.

5. ZONE BOUNDARIES: deterministically derived from the base candles only
   (never from the displacement candle):
       upper boundary = max(high) over the base candles
       lower boundary = min(low) over the base candles
   This is identical for Supply and Demand — the algorithms are symmetric,
   only the direction of displacement/structure-break differs.

A zone, once created, is immutable (boundaries are never modified) — only
its lifecycle STATE changes over time (see zones/lifecycle.py).
"""
from __future__ import annotations

import pandas as pd

from zones.lifecycle import Zone, ZoneType, candle_interacts, is_invalidated
from zones.swings import SwingRegistry


class ZoneDetector:
    def __init__(
        self,
        df: pd.DataFrame,
        atr: pd.Series,
        swings: SwingRegistry,
        base_max_candles: int,
        displacement_min_atr_multiplier: float,
        zone_invalidation_buffer_atr: float,
        zone_max_age_bars: int,
    ):
        self.df = df
        self.atr = atr
        self.swings = swings
        self.base_max_candles = base_max_candles
        self.displacement_min_atr_multiplier = displacement_min_atr_multiplier
        self.zone_invalidation_buffer_atr = zone_invalidation_buffer_atr
        self.zone_max_age_bars = zone_max_age_bars

        self.zones: list[Zone] = []
        self._next_id = 1

        self.n_demand_created = 0
        self.n_supply_created = 0

    # -- base identification -------------------------------------------------
    def _is_base_candle(self, j: int) -> bool:
        a = self.atr.iat[j]
        if pd.isna(a):
            return False
        rng = self.df["high"].iat[j] - self.df["low"].iat[j]
        return rng < a

    def _find_base_run(self, i: int) -> tuple[int, int] | None:
        """Return (base_start_index, base_end_index) inclusive, ending at
        i-1, or None if there is no base immediately preceding candle i."""
        if i - 1 < 0 or not self._is_base_candle(i - 1):
            return None
        end = i - 1
        start = end
        while start - 1 >= 0 and self._is_base_candle(start - 1):
            start -= 1
        # truncate to the most recent BASE_MAX_CANDLES candles
        if end - start + 1 > self.base_max_candles:
            start = end - self.base_max_candles + 1
        return start, end

    # -- displacement + structure break --------------------------------------
    def _check_demand(self, i: int) -> Zone | None:
        a = self.atr.iat[i]
        if pd.isna(a):
            return None
        o, c, h, l = (self.df[col].iat[i] for col in ("open", "close", "high", "low"))
        if not (c > o):
            return None
        displacement_range = h - l
        if displacement_range < a * self.displacement_min_atr_multiplier:
            return None

        swing = self.swings.last_confirmed_high_as_of(i)
        if swing is None or not (c > swing.price):
            return None

        base = self._find_base_run(i)
        if base is None:
            return None
        base_start, base_end = base
        upper = self.df["high"].iloc[base_start:base_end + 1].max()
        lower = self.df["low"].iloc[base_start:base_end + 1].min()

        return Zone(
            zone_id=self._next_id,
            zone_type=ZoneType.DEMAND,
            upper=upper,
            lower=lower,
            base_start_index=base_start,
            base_end_index=base_end,
            displacement_index=i,
            created_index=i,
            atr_at_creation=a,
        )

    def _check_supply(self, i: int) -> Zone | None:
        a = self.atr.iat[i]
        if pd.isna(a):
            return None
        o, c, h, l = (self.df[col].iat[i] for col in ("open", "close", "high", "low"))
        if not (c < o):
            return None
        displacement_range = h - l
        if displacement_range < a * self.displacement_min_atr_multiplier:
            return None

        swing = self.swings.last_confirmed_low_as_of(i)
        if swing is None or not (c < swing.price):
            return None

        base = self._find_base_run(i)
        if base is None:
            return None
        base_start, base_end = base
        upper = self.df["high"].iloc[base_start:base_end + 1].max()
        lower = self.df["low"].iloc[base_start:base_end + 1].min()

        return Zone(
            zone_id=self._next_id,
            zone_type=ZoneType.SUPPLY,
            upper=upper,
            lower=lower,
            base_start_index=base_start,
            base_end_index=base_end,
            displacement_index=i,
            created_index=i,
            atr_at_creation=a,
        )

    # -- public API: called once per closed candle, in chronological order --
    def update_existing_zones(self, i: int) -> None:
        """Update invalidation/expiry/testing state of all live zones using
        candle i. Must be called with i strictly greater than a zone's
        created_index for that zone to be eligible for interaction — this is
        enforced by the `i > zone.created_index` guard below."""
        close_i = self.df["close"].iat[i]
        low_i = self.df["low"].iat[i]
        high_i = self.df["high"].iat[i]
        a = self.atr.iat[i]

        for zone in self.zones:
            if zone.is_dead() or i <= zone.created_index:
                continue

            if not pd.isna(a) and is_invalidated(zone, close_i, a, self.zone_invalidation_buffer_atr):
                zone.state = zone.state.__class__.INVALIDATED
                zone.invalidated_index = i
                continue

            if zone.state == zone.state.__class__.ACTIVE:
                age = i - zone.created_index
                if age > self.zone_max_age_bars:
                    zone.state = zone.state.__class__.EXPIRED
                    zone.expired_index = i
                    continue

            if candle_interacts(low_i, high_i, zone):
                zone.retest_count += 1
                zone.tested_indices.append(i)
                zone.state = zone.state.__class__.TESTED

    def try_create_zones(self, i: int) -> list[Zone]:
        """Attempt to create new zones using candle i as the displacement
        candle. Returns the list of zones created (0, 1, or in principle 2,
        though a candle cannot realistically be both bullish and bearish)."""
        created = []
        demand = self._check_demand(i)
        if demand is not None:
            self.zones.append(demand)
            self._next_id += 1
            self.n_demand_created += 1
            created.append(demand)

        supply = self._check_supply(i)
        if supply is not None:
            self.zones.append(supply)
            self._next_id += 1
            self.n_supply_created += 1
            created.append(supply)

        return created

    def active_zones_as_of(self, i: int) -> list[Zone]:
        return [z for z in self.zones if z.is_tradeable() and i > z.created_index]
