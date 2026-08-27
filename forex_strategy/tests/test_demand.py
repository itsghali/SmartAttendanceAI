from indicators.atr import atr as compute_atr
from strategy.confirmation import confirms_demand
from tests.fixtures import demand_sequence
from zones.lifecycle import ZoneState, ZoneType
from zones.supply_demand import ZoneDetector
from zones.swings import SwingRegistry


def _build_detector(df, atr_period=3, swing_lookback=2):
    atr = compute_atr(df, atr_period)
    swings = SwingRegistry(df, swing_lookback)
    detector = ZoneDetector(
        df=df, atr=atr, swings=swings, base_max_candles=3,
        displacement_min_atr_multiplier=1.5, zone_invalidation_buffer_atr=0.1,
        zone_max_age_bars=100,
    )
    return detector, atr


def _run(df, detector):
    """Replay the exact confirmation/lifecycle order used by
    strategy/signals.py: confirmation is checked on zones that existed
    BEFORE candle i, then lifecycle/creation advance using candle i."""
    confirmations = {}
    for i in range(len(df)):
        zones_before = detector.active_zones_as_of(i)
        o, h, l, c = df["open"].iat[i], df["high"].iat[i], df["low"].iat[i], df["close"].iat[i]
        for zone in zones_before:
            if zone.zone_type == ZoneType.DEMAND and confirms_demand(o, h, l, c, zone):
                confirmations.setdefault(i, []).append(zone)
        detector.update_existing_zones(i)
        detector.try_create_zones(i)
    return confirmations


def test_valid_demand_zone_created_from_base_displacement_structure_break():
    df = demand_sequence()
    detector, _ = _build_detector(df)
    _run(df, detector)

    demand_zones = [z for z in detector.zones if z.zone_type == ZoneType.DEMAND]
    assert len(demand_zones) == 1
    zone = demand_zones[0]
    assert zone.created_index == 16
    assert abs(zone.upper - 101.7) < 1e-9
    assert abs(zone.lower - 100.8) < 1e-9


def test_demand_zone_interaction_without_confirmation_marks_tested_only():
    df = demand_sequence()
    detector, _ = _build_detector(df)
    confirmations = _run(df, detector)

    zone = detector.zones[0]
    assert zone.retest_count >= 1          # candle 19 interacted
    assert 19 not in confirmations         # but candle 19 is bearish -> no confirmation
    assert zone.state in (ZoneState.TESTED,)


def test_demand_confirmation_fires_on_bullish_close_back_above_zone():
    df = demand_sequence()
    detector, _ = _build_detector(df)
    confirmations = _run(df, detector)

    assert 20 in confirmations
    assert confirmations[20][0] is detector.zones[0]


def test_invalidated_demand_zone_can_never_generate_another_confirmation():
    df = demand_sequence()
    detector, _ = _build_detector(df)

    # Force an invalidating close well below the lower boundary.
    for i in range(len(df)):
        zones_before = detector.active_zones_as_of(i)
        detector.update_existing_zones(i)
        detector.try_create_zones(i)
        if i == 16:
            zone = detector.zones[0]
            zone.state = ZoneState.INVALIDATED
            zone.invalidated_index = i

    zone = detector.zones[0]
    assert zone.is_dead()
    # A dead zone is excluded from active_zones_as_of at every later index.
    assert zone not in detector.active_zones_as_of(len(df) - 1)
