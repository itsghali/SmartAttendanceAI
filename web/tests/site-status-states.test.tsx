import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import ExceptionsTable from "../components/site-status/ExceptionsTable";
import { AttendanceException } from "../lib/siteStatusService";

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
  };
}

describe("ExceptionsTable states", () => {
  afterEach(() => cleanup());

  it("shows the true-empty message when nobody is checked in", () => {
    render(
      <ExceptionsTable
        exceptions={[]}
        departmentByEmployee={new Map()}
        onOpenHistory={vi.fn()}
        loadError={null}
      />,
    );
    expect(screen.getByText("No one is checked in right now.")).toBeTruthy();
  });

  it("shows the error banner instead of any table when loadError is set", () => {
    render(
      <ExceptionsTable
        exceptions={[exception({})]}
        departmentByEmployee={new Map()}
        onOpenHistory={vi.fn()}
        loadError="Network error"
      />,
    );
    expect(screen.getByText("Network error")).toBeTruthy();
    expect(screen.queryByText("Alice Example")).toBeNull();
  });

  it("shows a distinct filtered-empty message, not the true-empty message, when filters zero out all groups", () => {
    render(
      <ExceptionsTable
        exceptions={[exception({})]}
        departmentByEmployee={new Map()}
        onOpenHistory={vi.fn()}
        loadError={null}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText("Search employee name or code…"), {
      target: { value: "nobody-matches-this" },
    });
    expect(screen.getByText(/No results match your filters/)).toBeTruthy();
    expect(screen.queryByText("No one is checked in right now.")).toBeNull();
  });

  it("renders the row when data is present and no filters are active", () => {
    render(
      <ExceptionsTable
        exceptions={[exception({ needs_attention: true })]}
        departmentByEmployee={new Map([["emp-1", "Engineering"]])}
        onOpenHistory={vi.fn()}
        loadError={null}
      />,
    );
    expect(screen.getByText("Alice Example")).toBeTruthy();
    expect(screen.getByRole("cell", { name: "Engineering" })).toBeTruthy();
    expect(screen.getByText("Needs attention")).toBeTruthy();
  });
});
