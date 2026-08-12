import { configureStore } from "@reduxjs/toolkit";
import { AxiosError, AxiosHeaders } from "axios";

import * as authService from "../services/authService";
import * as tokenStorage from "../services/tokenStorage";
import authReducer, { login, logout, restoreSession, sessionExpired } from "./authSlice";

jest.mock("../services/authService");
jest.mock("../services/tokenStorage");

function buildStore() {
  return configureStore({ reducer: { auth: authReducer } });
}

const USER = {
  id: "u1",
  email: "jane@example.com",
  full_name: "Jane Doe",
  role: "employee",
  is_active: true,
  is_verified: true,
};

describe("authSlice", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("login stores the returned user and marks the session authenticated", async () => {
    (authService.login as jest.Mock).mockResolvedValue(USER);

    const store = buildStore();
    await store.dispatch(login({ email: USER.email, password: "Password123" }));

    expect(store.getState().auth.user).toEqual(USER);
    expect(store.getState().auth.status).toBe("authenticated");
  });

  it("login failure leaves the session unauthenticated with an error", async () => {
    (authService.login as jest.Mock).mockRejectedValue(new Error("invalid email or password"));

    const store = buildStore();
    await store.dispatch(login({ email: USER.email, password: "wrong" }));

    expect(store.getState().auth.status).toBe("unauthenticated");
    expect(store.getState().auth.error).toBe("invalid email or password");
  });

  it("login 401 from the real API surfaces the backend detail, not the raw axios message", async () => {
    // Regression test: axios's own Error.message for this is the generic
    // "Request failed with status code 401" — the bug reported was that
    // string reaching the login screen instead of the backend's actual
    // "invalid email or password" detail.
    const axiosError = new AxiosError(
      "Request failed with status code 401",
      "ERR_BAD_REQUEST",
      undefined,
      undefined,
      {
        status: 401,
        statusText: "Unauthorized",
        headers: new AxiosHeaders(),
        config: { headers: new AxiosHeaders() },
        data: { detail: "invalid email or password" },
      },
    );
    (authService.login as jest.Mock).mockRejectedValue(axiosError);

    const store = buildStore();
    await store.dispatch(login({ email: USER.email, password: "wrong" }));

    expect(store.getState().auth.status).toBe("unauthenticated");
    expect(store.getState().auth.error).toBe("invalid email or password");
  });

  it("restoreSession wipes any stored token and always requires a fresh sign-in", async () => {
    // Shared field devices: a token surviving from a previous employee's
    // session must never silently authenticate the next app open.
    (tokenStorage.clearTokens as jest.Mock).mockResolvedValue(undefined);

    const store = buildStore();
    await store.dispatch(restoreSession());

    expect(tokenStorage.clearTokens).toHaveBeenCalled();
    expect(store.getState().auth.status).toBe("unauthenticated");
    expect(store.getState().auth.user).toBeNull();
    expect(authService.getMe).not.toHaveBeenCalled();
  });

  it("logout clears the user and marks unauthenticated", async () => {
    (authService.login as jest.Mock).mockResolvedValue(USER);
    (authService.logout as jest.Mock).mockResolvedValue(undefined);

    const store = buildStore();
    await store.dispatch(login({ email: USER.email, password: "Password123" }));
    await store.dispatch(logout());

    expect(store.getState().auth.user).toBeNull();
    expect(store.getState().auth.status).toBe("unauthenticated");
  });

  it("sessionExpired reducer clears the user", () => {
    const store = buildStore();
    store.dispatch(sessionExpired());

    expect(store.getState().auth.user).toBeNull();
    expect(store.getState().auth.status).toBe("unauthenticated");
  });
});
