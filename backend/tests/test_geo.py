from app.core.geo import Coordinates, haversine_distance_meters, is_within_geofence

OFFICE = Coordinates(latitude=36.8065, longitude=10.1815)  # Tunis — mirrors mobile/src/services/geofence.test.ts


def test_zero_distance_for_identical_coordinates():
    assert haversine_distance_meters(OFFICE, OFFICE) == 0.0


def test_within_geofence_when_inside_radius():
    nearby = Coordinates(latitude=36.8066, longitude=10.1815)  # ~11m north
    assert is_within_geofence(nearby, OFFICE, 50) is True


def test_outside_geofence_when_beyond_radius():
    far_away = Coordinates(latitude=36.82, longitude=10.1815)  # ~1.5km north
    assert is_within_geofence(far_away, OFFICE, 50) is False
