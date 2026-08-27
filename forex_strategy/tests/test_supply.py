from indicators.atr import atr as compute_atr
from strategy.confirmation import confirms_supply
from tests.fixtures import supply_sequence
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
    confirmations = {}
    for i in range(len(df)):
        zones_before = detector.active_zones_as_of(i)
        o, h, l, c = df["open"].iat[i], df["high"].iat[i], df["low"].iat[i], df["close"].iat[i]
        for zone in zones_before:
            if zone.zone_type == ZoneType.SUPPLY and confirms_supply(o, h, l, c, zone):
                confirmations.setdefault(i, []).append(zone)
        detector.update_existing_zones(i)
        detector.try_create_zones(i)
    return confirmations


def test_valid_supply_zone_is_the_mirror_image_of_demand():
    df = supply_sequence()
    detector, _ = _build_detector(df)
    _run(df, detector)

    supply_zones = [z for z in detector.zones if z.zone_type == ZoneType.SUPPLY]
    assert len(supply_zones) == 1
    zone = supply_zones[0]
    assert zone.created_index == 16
    # mirrored around axis=200: demand [100.8, 101.7] -> supply [98.3, 99.2]
    assert abs(zone.upper - (200.0 - 100.8)) < 1e-9
    assert abs(zone.lower - (200.0 - 101.7)) < 1e-9


def test_supply_confirmation_fires_on_bearish_close_back_below_zone():
    df = supply_sequence()
    detector, _ = _build_detector(df)
    confirmations = _run(df, detector)

    assert 20 in confirmations
    assert confirmations[20][0] is detector.zones[0]


def test_supply_zone_never_confirms_before_it_exists():
    df = supply_sequence()
    detector, _ = _build_detector(df)
    confirmations = _run(df, detector)
    assert all(idx > 16 for idx in confirmations)
