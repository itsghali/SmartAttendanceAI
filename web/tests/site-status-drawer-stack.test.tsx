import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const getEmployeeGeofenceHistory = vi.fn();
const getEmployeeFaceAttempts = vi.fn();
vi.mock("../lib/siteStatusService", () => ({
  getEmployeeGeofenceHistory: (...args: unknown[]) => getEmployeeGeofenceHistory(...args),
  getEmployeeFaceAttempts: (...args: unknown[]) => getEmployeeFaceAttempts(...args),
}));

import HistoryPanel from "../components/site-status/HistoryPanel";
import EventDetailsDrawer from "../components/site-status/EventDetailsDrawer";
import type { GeofenceEventSummary } from "../lib/siteStatusService";

function event(overrides: Partial<GeofenceEventSummary>): GeofenceEventSummary {
  return {
    id: "evt-1",
    event_type: "exit",
    geofence_name: "Site A",
    created_at: "2026-08-11T10:00:00Z",
    authorized_radius_meters: 50,
    duration_minutes: null,
    still_open: null,
    ...overrides,
  };
}

// Renders both panels stacked, the same way page.tsx does — HistoryPanel
// first, EventDetailsDrawer conditionally on top — to exercise the real
// focus-trap stack rather than each panel in isolation.
function StackedPanels({
  eventOpen,
  onCloseHistory,
  onCloseEvent,
}: {
  eventOpen: boolean;
  onCloseHistory: () => void;
  onCloseEvent: () => void;
}) {
  return (
    <>
      <button data-testid="outside-trigger">Outside trigger</button>
      <HistoryPanel
        employeeId="emp-1"
        employeeName="Alice Example"
        department="Engineering"
        currentStatus="live"
        sessionClosed={false}
        onClose={onCloseHistory}
        onOpenEvent={() => {}}
      />
      {eventOpen && (
        <EventDetailsDrawer event={event({})} employeeName="Alice Example" onClose={onCloseEvent} />
      )}
    </>
  );
}

describe("stacked drawer keyboard behavior", () => {
  beforeEach(() => {
    getEmployeeGeofenceHistory.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    getEmployeeFaceAttempts.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  });
  afterEach(() => cleanup());

  it("Escape closes the topmost panel (event drawer) first, not both at once", async () => {
    const onCloseHistory = vi.fn();
    const onCloseEvent = vi.fn();
    render(
      <StackedPanels eventOpen={true} onCloseHistory={onCloseHistory} onCloseEvent={onCloseEvent} />,
    );
    await waitFor(() => expect(getEmployeeGeofenceHistory).toHaveBeenCalled());

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onCloseEvent).toHaveBeenCalledTimes(1);
    expect(onCloseHistory).not.toHaveBeenCalled();
  });

  it("a second Escape (after the event drawer is gone) closes HistoryPanel", async () => {
    const onCloseHistory = vi.fn();
    const onCloseEvent = vi.fn();
    const { rerender } = render(
      <StackedPanels eventOpen={true} onCloseHistory={onCloseHistory} onCloseEvent={onCloseEvent} />,
    );
    await waitFor(() => expect(getEmployeeGeofenceHistory).toHaveBeenCalled());

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCloseEvent).toHaveBeenCalledTimes(1);

    // Simulate the parent responding to onCloseEvent by unmounting the drawer.
    rerender(
      <StackedPanels eventOpen={false} onCloseHistory={onCloseHistory} onCloseEvent={onCloseEvent} />,
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCloseHistory).toHaveBeenCalledTimes(1);
  });

  it("when only HistoryPanel is open, Escape closes it directly", async () => {
    const onCloseHistory = vi.fn();
    render(
      <StackedPanels eventOpen={false} onCloseHistory={onCloseHistory} onCloseEvent={vi.fn()} />,
    );
    await waitFor(() => expect(getEmployeeGeofenceHistory).toHaveBeenCalled());

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCloseHistory).toHaveBeenCalledTimes(1);
  });

  it("restores focus to the trigger element after HistoryPanel closes", async () => {
    const onCloseHistory = vi.fn();
    render(
      <>
        <button data-testid="trigger">Open</button>
      </>,
    );
    const trigger = screen.getByTestId("trigger");
    act(() => trigger.focus());
    expect(document.activeElement).toBe(trigger);

    const { unmount } = render(
      <HistoryPanel
        employeeId="emp-1"
        employeeName="Alice Example"
        department="Engineering"
        currentStatus="live"
        sessionClosed={false}
        onClose={onCloseHistory}
        onOpenEvent={() => {}}
      />,
    );
    await waitFor(() => expect(getEmployeeGeofenceHistory).toHaveBeenCalled());
    unmount();

    expect(document.activeElement).toBe(trigger);
  });
});
