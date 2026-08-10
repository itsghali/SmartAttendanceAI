const EARTH_RADIUS_METERS = 6371000;

export interface Coordinates {
  latitude: number;
  longitude: number;
}

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

export function haversineDistanceMeters(a: Coordinates, b: Coordinates): number {
  const dLat = toRadians(b.latitude - a.latitude);
  const dLon = toRadians(b.longitude - a.longitude);
  const lat1 = toRadians(a.latitude);
  const lat2 = toRadians(b.latitude);

  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));

  return EARTH_RADIUS_METERS * c;
}

export function isWithinGeofence(
  position: Coordinates,
  center: Coordinates,
  radiusMeters: number,
): boolean {
  return haversineDistanceMeters(position, center) <= radiusMeters;
}
