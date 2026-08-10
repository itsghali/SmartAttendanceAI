import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

import { api } from "../lib/api";
import { createGeofence, updateGeofence, setGeofenceActive } from "../lib/geofenceService";

describe("geofenceService", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("createGeofence posts the exact circle payload, unmodified", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: { id: "g1" } });
    await createGeofence({
      name: "HQ",
      boundary_type: "circle",
      center_latitude: 36.8,
      center_longitude: 10.18,
      radius_meters: 100,
      polygon_points: null,
    });
    expect(api.post).toHaveBeenCalledWith("/geofences", {
      name: "HQ",
      boundary_type: "circle",
      center_latitude: 36.8,
      center_longitude: 10.18,
      radius_meters: 100,
      polygon_points: null,
    });
  });

  it("updateGeofence PATCHes the site id with the full replacement payload", async () => {
    vi.mocked(api.patch).mockResolvedValueOnce({ data: { id: "g1" } });
    await updateGeofence("g1", {
      name: "Chantier",
      department_id: null,
      boundary_type: "polygon",
      center_latitude: null,
      center_longitude: null,
      radius_meters: null,
      polygon_points: [
        { latitude: 36.8, longitude: 10.18 },
        { latitude: 36.81, longitude: 10.18 },
        { latitude: 36.81, longitude: 10.19 },
      ],
    });
    expect(api.patch).toHaveBeenCalledWith(
      "/geofences/g1",
      expect.objectContaining({ boundary_type: "polygon", polygon_points: expect.any(Array) }),
    );
  });

  it("setGeofenceActive only touches is_active, not the site's geometry", async () => {
    vi.mocked(api.patch).mockResolvedValueOnce({ data: {} });
    await setGeofenceActive("g1", false);
    expect(api.patch).toHaveBeenCalledWith("/geofences/g1", { is_active: false });
  });
});
