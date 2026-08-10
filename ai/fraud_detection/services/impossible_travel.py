"""Impossible-travel heuristic: flags check-ins that imply physically
implausible speed between two consecutive locations."""

MAX_PLAUSIBLE_SPEED_KMH = 120.0


def required_speed_kmh(distance_km: float, elapsed_hours: float) -> float:
    if elapsed_hours <= 0:
        return float("inf")
    return distance_km / elapsed_hours


def impossible_travel_risk(
    distance_km: float,
    elapsed_hours: float,
    max_plausible_speed_kmh: float = MAX_PLAUSIBLE_SPEED_KMH,
) -> float:
    """Returns a risk score in [0, 1]. 0 = plausible, 1 = impossible."""
    speed = required_speed_kmh(distance_km, elapsed_hours)
    if speed <= max_plausible_speed_kmh:
        return 0.0
    return min(1.0, (speed - max_plausible_speed_kmh) / max_plausible_speed_kmh)
