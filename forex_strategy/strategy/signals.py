"""End-to-end, no-look-ahead signal generation for a single pair.

Pipeline (identical structure for BUY/Demand and SELL/Supply, per spec
section 17):

    zone (tradeable, created strictly before candle i)
        -> candle i interacts with zone AND confirms (bullish/bearish close
           back through the boundary)                          [confirmation]
        -> structural SL computed from zone + ATR[i]           [structural SL]
        -> entry is mechanically the next candle's open (i+1)  [entry rule]
        -> SL <= max_sl_pips ?                                 [hard filter]
        -> MA200[i] on the correct side of entry ?             [TP validity]
        -> RR >= min_rr ?                                      [RR filter]
        -> ACCEPTED  (else REJECTED, with every failing reason recorded)

Rejection reasons are evaluated independently (not short-circuited) so the
research statistics in section 27 ("rejected because SL > max", "...MA200
wrong side", "...RR insufficient") are not distorted by an arbitrary
priority order — a single setup can carry more than one simultaneous
reason. See risk/risk_reward.py for the rationale on using the raw
(cost-free) next-open as "entry" for these filters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

from indicators.atr import atr as compute_atr
from indicators.moving_average import sma
from risk.pips import price_diff_to_pips
from risk.risk_reward import check_max_sl_pips, check_min_rr, compute_risk_reward
from risk.stop_loss import structural_stop_loss
from risk.take_profit import take_profit_from_ma200, tp_direction_valid
from strategy.confirmation import confirms_demand, confirms_supply
from zones.lifecycle import Zone, ZoneType
from zones.supply_demand import ZoneDetector
from zones.swings import SwingRegistry


class RejectionReason(str, Enum):
    SL_TOO_LARGE = "SL_TOO_LARGE"
    MA200_WRONG_SIDE = "MA200_WRONG_SIDE"
    RR_INSUFFICIENT = "RR_INSUFFICIENT"
    ZERO_RISK = "ZERO_RISK"
    NO_NEXT_CANDLE = "NO_NEXT_CANDLE"


@dataclass
class SetupOutcome:
    pair: str
    direction: str                 # BUY | SELL
    zone: Zone
    confirmation_index: int
    confirmation_timestamp: pd.Timestamp
    entry_index: int | None
    entry_timestamp: pd.Timestamp | None
    raw_entry: float | None
    sl: float | None
    tp: float | None
    sl_pips: float | None
    tp_pips: float | None
    rr: float | None
    atr_at_confirmation: float
    ma200_at_confirmation: float
    accepted: bool
    rejection_reasons: list[RejectionReason] = field(default_factory=list)


@dataclass
class SignalGenerationResult:
    setups: list[SetupOutcome]
    n_demand_zones: int
    n_supply_zones: int
    n_retests: int
    swings: SwingRegistry
    zone_detector: ZoneDetector
    atr: pd.Series
    ma200: pd.Series


def generate_signals(
    pair: str,
    df: pd.DataFrame,
    cfg: dict,
    max_sl_pips: float | None = None,
    min_rr: float | None = None,
) -> SignalGenerationResult:
    pip_size = cfg["pairs"][pair]["pip_size"]
    max_sl_pips = cfg["max_sl_pips"] if max_sl_pips is None else max_sl_pips
    min_rr = cfg["min_rr"] if min_rr is None else min_rr

    atr = compute_atr(df, cfg["atr_period"])
    ma200 = sma(df, cfg["ma_period"])
    swings = SwingRegistry(df, cfg["swing_lookback"])
    detector = ZoneDetector(
        df=df,
        atr=atr,
        swings=swings,
        base_max_candles=cfg["base_max_candles"],
        displacement_min_atr_multiplier=cfg["displacement_min_atr_multiplier"],
        zone_invalidation_buffer_atr=cfg["zone_invalidation_buffer_atr"],
        zone_max_age_bars=cfg["zone_max_age_bars"],
    )

    setups: list[SetupOutcome] = []
    n = len(df)

    warmup = max(cfg["atr_period"], cfg["ma_period"], cfg["swing_lookback"] * 2 + 1)

    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    timestamps = df["timestamp"]

    for i in range(warmup, n):
        # 1) evaluate confirmation using zones that existed BEFORE candle i
        candidate_zones = detector.active_zones_as_of(i)
        o_i, h_i, l_i, c_i = opens[i], highs[i], lows[i], closes[i]
        a_i, ma_i = atr.iat[i], ma200.iat[i]

        for zone in candidate_zones:
            direction = None
            if zone.zone_type == ZoneType.DEMAND and confirms_demand(o_i, h_i, l_i, c_i, zone):
                direction = "BUY"
            elif zone.zone_type == ZoneType.SUPPLY and confirms_supply(o_i, h_i, l_i, c_i, zone):
                direction = "SELL"
            if direction is None:
                continue
            if pd.isna(a_i) or pd.isna(ma_i):
                continue  # indicators not warmed up; should not happen post-warmup guard

            setups.append(
                _evaluate_setup(
                    pair=pair,
                    direction=direction,
                    zone=zone,
                    i=i,
                    df=df,
                    timestamps=timestamps,
                    atr_at_confirmation=float(a_i),
                    ma200_at_confirmation=float(ma_i),
                    pip_size=pip_size,
                    sl_buffer_atr_multiplier=cfg["sl_buffer_atr_multiplier"],
                    max_sl_pips=max_sl_pips,
                    min_rr=min_rr,
                )
            )

        # 2) advance zone lifecycle using candle i (invalidation/testing/expiry)
        detector.update_existing_zones(i)
        # 3) attempt to create new zones using candle i as displacement
        detector.try_create_zones(i)

    n_retests = sum(z.retest_count for z in detector.zones)

    return SignalGenerationResult(
        setups=setups,
        n_demand_zones=detector.n_demand_created,
        n_supply_zones=detector.n_supply_created,
        n_retests=n_retests,
        swings=swings,
        zone_detector=detector,
        atr=atr,
        ma200=ma200,
    )


def _evaluate_setup(
    pair: str,
    direction: str,
    zone: Zone,
    i: int,
    df: pd.DataFrame,
    timestamps: pd.Series,
    atr_at_confirmation: float,
    ma200_at_confirmation: float,
    pip_size: float,
    sl_buffer_atr_multiplier: float,
    max_sl_pips: float,
    min_rr: float,
) -> SetupOutcome:
    sl = structural_stop_loss(zone, atr_at_confirmation, sl_buffer_atr_multiplier)
    tp = take_profit_from_ma200(ma200_at_confirmation)

    n = len(df)
    if i + 1 >= n:
        return SetupOutcome(
            pair=pair, direction=direction, zone=zone,
            confirmation_index=i, confirmation_timestamp=timestamps.iat[i],
            entry_index=None, entry_timestamp=None, raw_entry=None,
            sl=sl, tp=tp, sl_pips=None, tp_pips=None, rr=None,
            atr_at_confirmation=atr_at_confirmation, ma200_at_confirmation=ma200_at_confirmation,
            accepted=False, rejection_reasons=[RejectionReason.NO_NEXT_CANDLE],
        )

    entry_index = i + 1
    raw_entry = float(df["open"].iat[entry_index])

    risk, reward, rr = compute_risk_reward(raw_entry, sl, tp)
    sl_pips = price_diff_to_pips(raw_entry - sl, pip_size)
    tp_pips = price_diff_to_pips(tp - raw_entry, pip_size)

    reasons = []
    if risk <= 0:
        reasons.append(RejectionReason.ZERO_RISK)
    if not check_max_sl_pips(sl_pips, max_sl_pips):
        reasons.append(RejectionReason.SL_TOO_LARGE)
    if not tp_direction_valid(direction, tp, raw_entry):
        reasons.append(RejectionReason.MA200_WRONG_SIDE)
    if risk > 0 and not check_min_rr(rr, min_rr):
        reasons.append(RejectionReason.RR_INSUFFICIENT)

    accepted = len(reasons) == 0

    return SetupOutcome(
        pair=pair, direction=direction, zone=zone,
        confirmation_index=i, confirmation_timestamp=timestamps.iat[i],
        entry_index=entry_index, entry_timestamp=timestamps.iat[entry_index],
        raw_entry=raw_entry, sl=sl, tp=tp,
        sl_pips=sl_pips, tp_pips=tp_pips, rr=rr,
        atr_at_confirmation=atr_at_confirmation, ma200_at_confirmation=ma200_at_confirmation,
        accepted=accepted, rejection_reasons=reasons,
    )
