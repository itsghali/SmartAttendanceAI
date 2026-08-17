import { describe, expect, it } from "vitest";

import { formatExitDuration } from "../components/site-status/exitDuration";
import { GeofenceEventSummary } from "../lib/siteStatusService";

function exitEvent(overrides: Partial<GeofenceEventSummary>): GeofenceEventSummary {
  return {
    id: "evt-1",
    event_type: "exit",
    geofence_name: "HQ",
    created_at: "2026-08-13T09:00:00Z",
    authorized_radius_meters: 100,
    duration_minutes: null,
    still_open: null,
    ...overrides,
  };
}

describe("formatExitDuration", () => {
  it("returns null for non-exit rows regardless of duration fields", () => {
    const event = exitEvent({ event_type: "return", duration_minutes: 5, still_open: false });
    expect(formatExitDuration(event, Date.now())).toBeNull();
  });

  it("renders a closed exit's duration in minutes", () => {
    const event = exitEvent({ duration_minutes: 12, still_open: false });
    expect(formatExitDuration(event, Date.now())).toBe("12m");
  });

  it("renders a still-open exit as a live elapsed count from created_at", () => {
    const createdAt = new Date("2026-08-13T09:00:00Z");
    const event = exitEvent({ created_at: createdAt.toISOString(), still_open: true, duration_minutes: null });
    const nowMs = createdAt.getTime() + 4 * 60_000; // 4 minutes later
    expect(formatExitDuration(event, nowMs)).toBe("still outside 4m");
  });

  it("ticks up as nowMs advances, without any new data from the server", () => {
    const createdAt = new Date("2026-08-13T09:00:00Z");
    const event = exitEvent({ created_at: createdAt.toISOString(), still_open: true, duration_minutes: null });
    const atOneMinute = formatExitDuration(event, createdAt.getTime() + 1 * 60_000);
    const atFiveMinutes = formatExitDuration(event, createdAt.getTime() + 5 * 60_000);
    expect(atOneMinute).toBe("still outside 1m");
    expect(atFiveMinutes).toBe("still outside 5m");
  });
});
