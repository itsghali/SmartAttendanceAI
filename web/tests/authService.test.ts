import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({
  api: {
    post: vi.fn(),
    get: vi.fn(),
  },
}));

import { api } from "../lib/api";
import { getAccessToken, getRefreshToken, clearTokens } from "../lib/tokenStorage";
import { login } from "../lib/authService";

describe("authService.login", () => {
  afterEach(() => {
    clearTokens();
    vi.clearAllMocks();
  });

  it("stores tokens and returns the current user", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { access_token: "access-123", refresh_token: "refresh-456" },
    });
    vi.mocked(api.get).mockResolvedValueOnce({
      data: {
        id: "u1",
        email: "hr@example.com",
        full_name: "HR Person",
        role: "hr_manager",
        is_active: true,
        is_verified: true,
      },
    });

    const user = await login("hr@example.com", "TempPass123");

    expect(api.post).toHaveBeenCalledWith("/auth/login", {
      email: "hr@example.com",
      password: "TempPass123",
    });
    expect(getAccessToken()).toBe("access-123");
    expect(getRefreshToken()).toBe("refresh-456");
    expect(user.role).toBe("hr_manager");
  });
});
