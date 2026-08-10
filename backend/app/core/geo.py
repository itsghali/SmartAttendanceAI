import math
from dataclasses import dataclass

# Ports mobile/src/services/geofence.ts 1:1 — keep both in sync if either changes.

EARTH_RADIUS_METERS = 6371000.0


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float


def _to_radians(degrees: float) -> float:
    return degrees * math.pi / 180


def haversine_distance_meters(a: Coordinates, b: Coordinates) -> float:
    d_lat = _to_radians(b.latitude - a.latitude)
    d_lon = _to_radians(b.longitude - a.longitude)
    lat1 = _to_radians(a.latitude)
    lat2 = _to_radians(b.latitude)

    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))

    return EARTH_RADIUS_METERS * c


def is_within_geofence(position: Coordinates, center: Coordinates, radius_meters: float) -> bool:
    return haversine_distance_meters(position, center) <= radius_meters


def polygon_centroid(points: list[Coordinates]) -> Coordinates:
    return Coordinates(
        latitude=sum(p.latitude for p in points) / len(points),
        longitude=sum(p.longitude for p in points) / len(points),
    )


def is_within_polygon(position: Coordinates, points: list[Coordinates]) -> bool:
    """Ray-casting point-in-polygon test. `points` are the polygon vertices in
    order (not closed — first/last point are not the same). Treats lat/lng as
    a flat plane, adequate for a single-chantier-scale boundary (not the
    globe-spanning case PostGIS would be needed for — see TODOS.md)."""
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i].longitude, points[i].latitude
        xj, yj = points[j].longitude, points[j].latitude
        if ((yi > position.latitude) != (yj > position.latitude)) and (
            position.longitude
            < (xj - xi) * (position.latitude - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside
