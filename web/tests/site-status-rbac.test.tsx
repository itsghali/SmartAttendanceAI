import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

const useAuthMock = vi.fn();
vi.mock("../lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock("../lib/siteStatusService", () => ({
  listAttendanceExceptions: vi.fn().mockResolvedValue({ items: [], needs_attention_count: 0, total: 0 }),
  getEmployeeGeofenceHistory: vi.fn(),
  getEmployeeFaceAttempts: vi.fn(),
}));
vi.mock("../lib/employeeService", () => ({
  listEmployees: vi.fn().mockResolvedValue([]),
}));
vi.mock("../lib/departmentService", () => ({
  listDepartments: vi.fn().mockResolvedValue([]),
}));
vi.mock("../lib/problemReportService", () => ({
  listProblemReports: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 }),
}));

import SiteStatusPage from "../app/site-status/page";

// Regression guard: the allowedRoles gate must survive the component-
// extraction refactor (KpiRow/ExceptionsTable/EventDetailsDrawer/HistoryPanel
// pulled out of the monolithic page.tsx).
describe("site-status page RBAC gate", () => {
  afterEach(() => {
    cleanup();
    replace.mockClear();
    useAuthMock.mockReset();
  });

  it.each(["hr_manager", "admin", "super_admin"])(
    "renders the page for role %s",
    async (role) => {
      useAuthMock.mockReturnValue({
        user: { id: "u1", email: "hr@example.com", full_name: "HR Person", role },
        loading: false,
        logout: vi.fn(),
      });
      render(<SiteStatusPage />);
      expect(await screen.findByText("Geofence Monitoring")).toBeTruthy();
      expect(replace).not.toHaveBeenCalledWith("/login");
    },
  );

  it("redirects a supervisor-role user away, does not render the page", () => {
    useAuthMock.mockReturnValue({
      user: { id: "u2", email: "sup@example.com", full_name: "Supervisor", role: "supervisor" },
      loading: false,
      logout: vi.fn(),
    });
    render(<SiteStatusPage />);
    expect(screen.queryByText("Geofence Monitoring")).toBeNull();
  });

  it("redirects an unauthenticated user to /login", () => {
    useAuthMock.mockReturnValue({ user: null, loading: false, logout: vi.fn() });
    render(<SiteStatusPage />);
    expect(replace).toHaveBeenCalledWith("/login");
  });
});
