from fraud_detection.services.impossible_travel import (
    impossible_travel_risk,
    required_speed_kmh,
)


def test_plausible_travel_scores_zero():
    # 10km in 1 hour = 10km/h, well under the 120km/h threshold
    assert impossible_travel_risk(distance_km=10, elapsed_hours=1) == 0.0


def test_impossible_travel_scores_high():
    # 1000km in 0.5h = 2000km/h, far beyond plausible ground travel
    risk = impossible_travel_risk(distance_km=1000, elapsed_hours=0.5)
    assert risk == 1.0


def test_required_speed_handles_zero_elapsed_time():
    assert required_speed_kmh(distance_km=5, elapsed_hours=0) == float("inf")
