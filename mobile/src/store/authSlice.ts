import { createAsyncThunk, createSlice, PayloadAction } from "@reduxjs/toolkit";

import * as authService from "../services/authService";
import { clearTokens } from "../services/tokenStorage";
import { extractErrorMessage } from "../utils/apiError";
import type { User } from "../services/authService";

export type AuthStatus = "idle" | "loading" | "authenticated" | "unauthenticated";

interface AuthState {
  user: User | null;
  status: AuthStatus;
  error: string | null;
}

const initialState: AuthState = {
  user: null,
  status: "idle",
  error: null,
};

// Deliberately does not trust a stored token, even a valid one — this app
// requires sign-in on every app open (field devices are often shared between
// employees), so any leftover session from a previous run is wiped rather
// than silently resumed.
export const restoreSession = createAsyncThunk("auth/restoreSession", async () => {
  await clearTokens();
  return null;
});

export const login = createAsyncThunk(
  "auth/login",
  async ({ email, password }: { email: string; password: string }, { rejectWithValue }) => {
    try {
      return await authService.login(email, password);
    } catch (error) {
      return rejectWithValue(extractErrorMessage(error));
    }
  },
);

export const logout = createAsyncThunk("auth/logout", async () => {
  await authService.logout();
});

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    sessionExpired(state) {
      state.user = null;
      state.status = "unauthenticated";
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(restoreSession.pending, (state) => {
        state.status = "loading";
      })
      .addCase(restoreSession.fulfilled, (state, action: PayloadAction<User | null>) => {
        state.user = action.payload;
        state.status = action.payload ? "authenticated" : "unauthenticated";
      })
      .addCase(restoreSession.rejected, (state) => {
        state.user = null;
        state.status = "unauthenticated";
      })
      .addCase(login.pending, (state) => {
        state.status = "loading";
        state.error = null;
      })
      .addCase(login.fulfilled, (state, action: PayloadAction<User>) => {
        state.user = action.payload;
        state.status = "authenticated";
      })
      .addCase(login.rejected, (state, action) => {
        state.status = "unauthenticated";
        state.error = (action.payload as string) ?? "login failed";
      })
      .addCase(logout.fulfilled, (state) => {
        state.user = null;
        state.status = "unauthenticated";
      });
  },
});

export const { sessionExpired } = authSlice.actions;
export default authSlice.reducer;
