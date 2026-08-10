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

import RequireAuth from "../components/RequireAuth";

describe("RequireAuth", () => {
  afterEach(() => {
    cleanup();
    replace.mockClear();
    useAuthMock.mockReset();
  });

  it("redirects to /login and renders nothing when there is no user", () => {
    useAuthMock.mockReturnValue({ user: null, loading: false });
    render(
      <RequireAuth>
        <div>secret content</div>
      </RequireAuth>,
    );
    expect(screen.queryByText("secret content")).toBeNull();
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("renders children once a user is present, without redirecting", () => {
    useAuthMock.mockReturnValue({
      user: { id: "u1", email: "hr@example.com", full_name: "HR", role: "hr_manager" },
      loading: false,
    });
    render(
      <RequireAuth>
        <div>secret content</div>
      </RequireAuth>,
    );
    expect(screen.getByText("secret content")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows a loading state and does not redirect while auth is still resolving", () => {
    useAuthMock.mockReturnValue({ user: null, loading: true });
    render(
      <RequireAuth>
        <div>secret content</div>
      </RequireAuth>,
    );
    expect(screen.queryByText("secret content")).toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });
});
