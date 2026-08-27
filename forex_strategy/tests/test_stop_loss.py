from risk.stop_loss import structural_stop_loss
from zones.lifecycle import Zone, ZoneType


def _zone(zone_type):
    return Zone(
        zone_id=1, zone_type=zone_type, upper=1.10040, lower=1.10000,
        base_start_index=0, base_end_index=1, displacement_index=2, created_index=2,
        atr_at_creation=0.0010,
    )


def test_buy_sl_is_below_demand_zone_lower_boundary():
    zone = _zone(ZoneType.DEMAND)
    sl = structural_stop_loss(zone, atr_at_confirmation=0.0010, sl_buffer_atr_multiplier=0.1)
    assert sl < zone.lower
    assert abs(sl - (zone.lower - 0.0001)) < 1e-9


def test_sell_sl_is_above_supply_zone_upper_boundary():
    zone = _zone(ZoneType.SUPPLY)
    sl = structural_stop_loss(zone, atr_at_confirmation=0.0010, sl_buffer_atr_multiplier=0.1)
    assert sl > zone.upper
    assert abs(sl - (zone.upper + 0.0001)) < 1e-9
