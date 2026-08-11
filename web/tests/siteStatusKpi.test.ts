import { describe, expect, it } from "vitest";

import { computeKpis } from "../components/site-status/kpi";
import { AttendanceException } from "../lib/siteStatusService";

function exception(overrides: Partial<AttendanceException>): AttendanceException {
  return {
    employee_id: "emp-1",
    employee_full_name: "Test Employee",
    employee_code: "EMP-0001",
    attendance_id: "att-1",
    check_in_at: "2026-08-11T08:00:00Z",
    monitoring_status: "live",
    needs_attention: false,
    last_event_type: null,
    last_event_at: null,
    geofence_name: null,
    ...overrides,
  };
}

describe("computeKpis", () => {
  it("counts Currently Outside and Stale Signals from different fields", () => {
    const exceptions = [
      exception({ attendance_id: "a1", needs_attention: true, monitoring_status: "live" }),
      exception({ attendance_id: "a2", needs_attention: false, monitoring_status: "stale" }),
      exception({ attendance_id: "a3", needs_attention: false, monitoring_status: "on_break" }),
    ];
    expect(computeKpis(exceptions)).toEqual({ currentlyOutside: 1, staleSignals: 1 });
  });

  it("does not collapse to the same number when only one signal is present", () => {
    // Regression guard for the duplicate-KPI defect caught during design
    // review: two cards reading the same boolean always show an identical
    // number. currentlyOutside and staleSignals must be able to diverge.
    const exceptions = [
      exception({ attendance_id: "a1", needs_attention: true, monitoring_status: "live" }),
      exception({ attendance_id: "a2", needs_attention: true, monitoring_status: "live" }),
    ];
    const kpis = computeKpis(exceptions);
    expect(kpis.currentlyOutside).toBe(2);
    expect(kpis.staleSignals).toBe(0);
    expect(kpis.currentlyOutside).not.toBe(kpis.staleSignals);
  });

  it("counts a row that is both flagged AND stale in both counts (no subgroup scoping)", () => {
    // Regression guard for the undercount risk caught during eng review:
    // an earlier draft scoped "Stale Signals" to the roster subgroup,
    // which is mutually exclusive with needs_attention client-side —
    // any row that could be both would have silently vanished from the
    // stale count. computeKpis reads the whole array, not a subgroup.
    const exceptions = [
      exception({ attendance_id: "a1", needs_attention: true, monitoring_status: "stale" }),
    ];
    expect(computeKpis(exceptions)).toEqual({ currentlyOutside: 1, staleSignals: 1 });
  });

  it("returns zero for both on an empty list", () => {
    expect(computeKpis([])).toEqual({ currentlyOutside: 0, staleSignals: 0 });
  });
});
