import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import { AxiosError } from "axios";

import * as attendanceService from "../services/attendanceService";
import { getCurrentPosition } from "../services/locationService";
import type { Attendance, BreakPeriod } from "../services/attendanceService";

export type AttendanceActionStatus = "idle" | "locating" | "submitting";

interface AttendanceState {
  /** The session open right now — null when checked out of every site. */
  today: Attendance | null;
  /** Every session that started today, finished ones included. */
  sessions: Attendance[];
  loadStatus: "idle" | "loading" | "loaded" | "error";
  loadError: string | null;
  actionStatus: AttendanceActionStatus;
  actionError: string | null;
}

const initialState: AttendanceState = {
  today: null,
  sessions: [],
  loadStatus: "idle",
  loadError: null,
  actionStatus: "idle",
  actionError: null,
};

function extractErrorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") {
      return detail;
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "something went wrong";
}

export const fetchToday = createAsyncThunk(
  "attendance/fetchToday",
  async (_: void, { rejectWithValue }) => {
    try {
      return await attendanceService.getTodayAttendance();
    } catch (error) {
      return rejectWithValue(extractErrorMessage(error));
    }
  },
);

export const checkIn = createAsyncThunk(
  "attendance/checkIn",
  async (selfieBase64: string | undefined, { rejectWithValue }) => {
    try {
      const position = await getCurrentPosition();
      return await attendanceService.checkIn({
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy_meters: position.accuracyMeters,
        selfie_base64: selfieBase64,
        is_mock_location: position.isMocked,
      });
    } catch (error) {
      return rejectWithValue(extractErrorMessage(error));
    }
  },
);

export const checkOut = createAsyncThunk(
  "attendance/checkOut",
  async (selfieBase64: string | undefined, { rejectWithValue }) => {
    try {
      const position = await getCurrentPosition();
      return await attendanceService.checkOut({
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy_meters: position.accuracyMeters,
        selfie_base64: selfieBase64,
      });
    } catch (error) {
      return rejectWithValue(extractErrorMessage(error));
    }
  },
);

// Breaks are geofence- and face-gated exactly like check-in and check-out —
// live position and a fresh selfie are both required.
export const startBreak = createAsyncThunk(
  "attendance/startBreak",
  async (selfieBase64: string | undefined, { rejectWithValue }) => {
    try {
      const position = await getCurrentPosition();
      return await attendanceService.startBreak({
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy_meters: position.accuracyMeters,
        selfie_base64: selfieBase64,
      });
    } catch (error) {
      return rejectWithValue(extractErrorMessage(error));
    }
  },
);

export const endBreak = createAsyncThunk(
  "attendance/endBreak",
  async (selfieBase64: string | undefined, { rejectWithValue }) => {
    try {
      const position = await getCurrentPosition();
      return await attendanceService.endBreak({
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy_meters: position.accuracyMeters,
        selfie_base64: selfieBase64,
      });
    } catch (error) {
      return rejectWithValue(extractErrorMessage(error));
    }
  },
);

function upsertSession(state: AttendanceState, session: Attendance): void {
  const index = state.sessions.findIndex((s) => s.id === session.id);
  if (index >= 0) {
    state.sessions[index] = session;
  } else {
    state.sessions.push(session);
  }
}

function applyBreakUpdate(state: AttendanceState, breakPeriod: BreakPeriod): void {
  if (!state.today) {
    return;
  }
  const existingIndex = state.today.breaks.findIndex((b) => b.id === breakPeriod.id);
  if (existingIndex >= 0) {
    state.today.breaks[existingIndex] = breakPeriod;
  } else {
    state.today.breaks.push(breakPeriod);
  }
}

const attendanceSlice = createSlice({
  name: "attendance",
  initialState,
  reducers: {
    resetAttendanceState() {
      return initialState;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchToday.pending, (state) => {
        state.loadStatus = "loading";
        state.loadError = null;
      })
      .addCase(fetchToday.fulfilled, (state, action) => {
        state.loadStatus = "loaded";
        state.today = action.payload.current;
        state.sessions = action.payload.sessions;
      })
      .addCase(fetchToday.rejected, (state, action) => {
        state.loadStatus = "error";
        state.loadError = (action.payload as string) ?? "failed to load today's attendance";
      });

    for (const thunk of [checkIn, checkOut]) {
      builder
        .addCase(thunk.pending, (state) => {
          state.actionStatus = "submitting";
          state.actionError = null;
        })
        .addCase(thunk.rejected, (state, action) => {
          state.actionStatus = "idle";
          state.actionError = (action.payload as string) ?? "action failed";
        });
    }

    builder
      .addCase(checkIn.fulfilled, (state, action) => {
        state.actionStatus = "idle";
        state.today = action.payload;
        upsertSession(state, action.payload);
      })
      // Checking out ends the session but does NOT end the day — the employee
      // may drive to another chantier and check in again, so `today` clears
      // while the finished session stays in the list.
      .addCase(checkOut.fulfilled, (state, action) => {
        state.actionStatus = "idle";
        state.today = null;
        upsertSession(state, action.payload);
      });

    for (const thunk of [startBreak, endBreak]) {
      builder
        .addCase(thunk.pending, (state) => {
          state.actionStatus = "submitting";
          state.actionError = null;
        })
        .addCase(thunk.fulfilled, (state, action) => {
          state.actionStatus = "idle";
          applyBreakUpdate(state, action.payload);
        })
        .addCase(thunk.rejected, (state, action) => {
          state.actionStatus = "idle";
          state.actionError = (action.payload as string) ?? "action failed";
        });
    }
  },
});

export const { resetAttendanceState } = attendanceSlice.actions;
export default attendanceSlice.reducer;
