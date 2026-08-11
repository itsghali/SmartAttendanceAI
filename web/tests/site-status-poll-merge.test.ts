import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

const listAttendanceExceptions = vi.fn();
vi.mock("../lib/siteStatusService", () => ({
  listAttendanceExceptions: (...args: unknown[]) => listAttendanceExceptions(...args),
}));

import { usePollingExceptions } from "../components/site-status/usePollingExceptions";
import type { AttendanceException } from "../lib/siteStatusService";

function exception(overrides: Partial<AttendanceException>): AttendanceException {
  return {
    employee_id: "emp-1",
    employee_full_name: "Alice Example",
    employee_code: "EMP-0001",
    attendance_id: "att-1",
    check_in_at: "2026-08-11T08:00:00Z",
    monitoring_status: "live",
    needs_attention: false,
    last_event_type: "enter",
    last_event_at: "2026-08-11T08:00:00Z",
    geofence_name: "Site A",
    ...overrides,
  } as AttendanceException;
}

describe("usePollingExceptions", () => {
  beforeEach(() => {
    listAttendanceExceptions.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("preserves object identity for a row whose data is unchanged across a poll", async () => {
    const rowV1 = exception({});
    listAttendanceExceptions.mockResolvedValueOnce({
      items: [rowV1],
      needs_attention_count: 0,
      total: 1,
    });

    const { result } = renderHook(() => usePollingExceptions(30_000));
    await waitFor(() => expect(result.current.items).toHaveLength(1));
    const firstRef = result.current.items[0];

    // Second poll response is a NEW object with identical field values —
    // the merge must reuse the old reference, not the new object.
    const rowV1Identical = exception({});
    listAttendanceExceptions.mockResolvedValueOnce({
      items: [rowV1Identical],
      needs_attention_count: 0,
      total: 1,
    });
    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.items[0]).toBe(firstRef);
    expect(result.current.items[0]).not.toBe(rowV1Identical);
  });

  it("uses the new object when a row's data actually changed", async () => {
    listAttendanceExceptions.mockResolvedValueOnce({
      items: [exception({ monitoring_status: "live" })],
      needs_attention_count: 0,
      total: 1,
    });
    const { result } = renderHook(() => usePollingExceptions(30_000));
    await waitFor(() => expect(result.current.items).toHaveLength(1));

    const changed = exception({ monitoring_status: "stale" });
    listAttendanceExceptions.mockResolvedValueOnce({
      items: [changed],
      needs_attention_count: 0,
      total: 1,
    });
    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.items[0].monitoring_status).toBe("stale");
  });

  it("ignores a stale/out-of-order response that resolves after a newer request already applied", async () => {
    // Let mount's own initial fetch settle first, so the race below is
    // entirely under this test's control (not racing the mount effect's
    // own setTimeout(load, 0)).
    listAttendanceExceptions.mockResolvedValueOnce({
      items: [exception({ employee_full_name: "Initial" })],
      needs_attention_count: 0,
      total: 1,
    });
    const { result } = renderHook(() => usePollingExceptions(30_000));
    await waitFor(() => expect(result.current.items[0]?.employee_full_name).toBe("Initial"));

    // A slow request starts (seq N) and stays pending.
    let resolveSlow: (v: unknown) => void = () => {};
    const slowPromise = new Promise((resolve) => {
      resolveSlow = resolve;
    });
    listAttendanceExceptions.mockReturnValueOnce(slowPromise);
    let slowRequest: Promise<void> | undefined;
    act(() => {
      slowRequest = result.current.refresh();
    });

    // A newer request (seq N+1) starts and resolves first — must win.
    listAttendanceExceptions.mockResolvedValueOnce({
      items: [exception({ employee_full_name: "Fast Newer Response" })],
      needs_attention_count: 0,
      total: 1,
    });
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.items[0]?.employee_full_name).toBe("Fast Newer Response");

    // The stale slow request finally resolves — its data must be discarded
    // because a newer request already applied.
    await act(async () => {
      resolveSlow({
        items: [exception({ employee_full_name: "Stale Slow Response" })],
        needs_attention_count: 0,
        total: 1,
      });
      await slowRequest;
    });

    expect(result.current.items[0]?.employee_full_name).toBe("Fast Newer Response");
  });
});
