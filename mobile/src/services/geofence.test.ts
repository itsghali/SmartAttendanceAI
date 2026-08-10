import { haversineDistanceMeters, isWithinGeofence } from "./geofence";

const OFFICE = { latitude: 36.8065, longitude: 10.1815 }; // Tunis

describe("geofence", () => {
  it("returns ~0 distance for identical coordinates", () => {
    expect(haversineDistanceMeters(OFFICE, OFFICE)).toBeCloseTo(0, 3);
  });

  it("is within geofence when inside the radius", () => {
    const nearby = { latitude: 36.8066, longitude: 10.1815 }; // ~11m north
    expect(isWithinGeofence(nearby, OFFICE, 50)).toBe(true);
  });

  it("is outside geofence when beyond the radius", () => {
    const farAway = { latitude: 36.82, longitude: 10.1815 }; // ~1.5km north
    expect(isWithinGeofence(farAway, OFFICE, 50)).toBe(false);
  });
});
