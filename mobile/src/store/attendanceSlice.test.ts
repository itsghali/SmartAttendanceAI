import { configureStore } from "@reduxjs/toolkit";
import { AxiosError } from "axios";

import * as attendanceService from "../services/attendanceService";
import * as deviceIntegrityService from "../services/deviceIntegrityService";
import * as locationService from "../services/locationService";
import attendanceReducer, {
  checkIn,
  checkOut,
  endBreak,
  fetchToday,
  startBreak,
} from "./attendanceSlice";

jest.mock("../services/attendanceService");
jest.mock("../services/locationService");
jest.mock("../services/deviceIntegrityService");

function buildStore() {
  return configureStore({ reducer: { attendance: attendanceReducer } });
}

const POSITION = { latitude: 36.8065, longitude: 10.1815, accuracyMeters: 10, isMocked: false };

describe("attendanceSlice", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (deviceIntegrityService.checkIsJailbroken as jest.Mock).mockResolvedValue(false);
  });

  it("fetchToday populates the open session and today's session list", async () => {
    const record = { id: "a1", breaks: [] } as any;
    (attendanceService.getTodayAttendance as jest.Mock).mockResolvedValue({
      current: record,
      sessions: [record],
    });

    const store = buildStore();
    await store.dispatch(fetchToday());

    expect(store.getState().attendance.today).toEqual(record);
    expect(store.getState().attendance.sessions).toEqual([record]);
    expect(store.getState().attendance.loadStatus).toBe("loaded");
  });

  it("checkIn fetches the current position and submits it with the captured selfie", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    const record = { id: "a1", status: "present", breaks: [] } as any;
    (attendanceService.checkIn as jest.Mock).mockResolvedValue(record);

    const store = buildStore();
    await store.dispatch(checkIn("base64-selfie-data"));

    expect(attendanceService.checkIn).toHaveBeenCalledWith({
      latitude: POSITION.latitude,
      longitude: POSITION.longitude,
      accuracy_meters: POSITION.accuracyMeters,
      selfie_base64: "base64-selfie-data",
      is_mock_location: false,
      is_jailbroken: false,
    });
    expect(store.getState().attendance.today).toEqual(record);
    expect(store.getState().attendance.actionStatus).toBe("idle");
  });

  it("checkIn forwards isJailbroken=true so the backend can flag the row for HR review", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    (deviceIntegrityService.checkIsJailbroken as jest.Mock).mockResolvedValue(true);
    const record = { id: "a1", status: "present", breaks: [] } as any;
    (attendanceService.checkIn as jest.Mock).mockResolvedValue(record);

    const store = buildStore();
    await store.dispatch(checkIn("base64-selfie-data"));

    expect(attendanceService.checkIn).toHaveBeenCalledWith(
      expect.objectContaining({ is_jailbroken: true }),
    );
    // Unlike a mocked location, a jailbreak signal flags rather than blocks —
    // the check-in still succeeds.
    expect(store.getState().attendance.today).toEqual(record);
  });

  it("checkIn forwards isMocked=true so the backend can refuse a spoofed GPS fix", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue({
      ...POSITION,
      isMocked: true,
    });
    const axiosError = new AxiosError("Request failed");
    axiosError.response = {
      data: { detail: "this device is reporting a mocked/fake location — check-in refused" },
    } as any;
    (attendanceService.checkIn as jest.Mock).mockRejectedValue(axiosError);

    const store = buildStore();
    await store.dispatch(checkIn("base64-selfie-data"));

    expect(attendanceService.checkIn).toHaveBeenCalledWith(
      expect.objectContaining({ is_mock_location: true }),
    );
    expect(store.getState().attendance.actionError).toBe(
      "this device is reporting a mocked/fake location — check-in refused",
    );
  });

  it("checkIn surfaces the backend's geofence rejection detail on failure", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    const axiosError = new AxiosError("Request failed");
    axiosError.response = { data: { detail: "location is outside every eligible geofence" } } as any;
    (attendanceService.checkIn as jest.Mock).mockRejectedValue(axiosError);

    const store = buildStore();
    await store.dispatch(checkIn(undefined));

    expect(store.getState().attendance.actionError).toBe(
      "location is outside every eligible geofence",
    );
    expect(store.getState().attendance.today).toBeNull();
  });

  it("checkIn surfaces a face-verification rejection the same generic way", async () => {
    // Proves extractErrorMessage already covers the new face-gated rejection
    // reasons without any new client-side error plumbing.
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    const axiosError = new AxiosError("Request failed");
    axiosError.response = { data: { detail: "face did not match enrolled profile" } } as any;
    (attendanceService.checkIn as jest.Mock).mockRejectedValue(axiosError);

    const store = buildStore();
    await store.dispatch(checkIn("base64-selfie-data"));

    expect(store.getState().attendance.actionError).toBe("face did not match enrolled profile");
  });

  it("checkOut ends the session but keeps it in today's list", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    const record = { id: "a1", check_out_at: "2026-01-01T17:00:00Z", breaks: [] } as any;
    (attendanceService.checkOut as jest.Mock).mockResolvedValue(record);

    const store = buildStore();
    await store.dispatch(checkOut());

    expect(attendanceService.checkOut).toHaveBeenCalled();
    // Checking out of a chantier does not end the day — the employee can check
    // in at the next one, so the open session clears rather than going "done".
    expect(store.getState().attendance.today).toBeNull();
    expect(store.getState().attendance.sessions).toEqual([record]);
  });

  it("a second chantier the same day opens a new session alongside the first", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    const first = { id: "a1", check_out_at: "2026-01-01T12:00:00Z", breaks: [] } as any;
    const second = { id: "a2", check_out_at: null, breaks: [] } as any;
    (attendanceService.checkOut as jest.Mock).mockResolvedValue(first);
    (attendanceService.checkIn as jest.Mock).mockResolvedValue(second);

    const store = buildStore();
    await store.dispatch(checkOut());
    await store.dispatch(checkIn());

    expect(store.getState().attendance.today).toEqual(second);
    expect(store.getState().attendance.sessions.map((s) => s.id)).toEqual(["a1", "a2"]);
  });

  it("startBreak appends the new break period to today's record", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    const breakPeriod = { id: "b1", break_start_at: "2026-01-01T12:00:00Z", break_end_at: null };
    (attendanceService.startBreak as jest.Mock).mockResolvedValue(breakPeriod);

    const store = buildStore();
    // seed an open session via fetchToday first
    const open = { id: "a1", breaks: [] } as any;
    (attendanceService.getTodayAttendance as jest.Mock).mockResolvedValue({
      current: open,
      sessions: [open],
    });
    await store.dispatch(fetchToday());

    await store.dispatch(startBreak());

    expect(store.getState().attendance.today?.breaks).toEqual([breakPeriod]);
  });

  it("startBreak submits the current position — breaks are geofence-gated too", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    (attendanceService.startBreak as jest.Mock).mockResolvedValue({
      id: "b1",
      break_start_at: "2026-01-01T12:00:00Z",
      break_end_at: null,
    });

    const store = buildStore();
    await store.dispatch(startBreak());

    expect(locationService.getCurrentPosition).toHaveBeenCalled();
    expect(attendanceService.startBreak).toHaveBeenCalledWith({
      latitude: POSITION.latitude,
      longitude: POSITION.longitude,
      accuracy_meters: POSITION.accuracyMeters,
    });
  });

  it("endBreak submits the current position", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    (attendanceService.endBreak as jest.Mock).mockResolvedValue({
      id: "b1",
      break_start_at: "2026-01-01T12:00:00Z",
      break_end_at: "2026-01-01T12:30:00Z",
    });

    const store = buildStore();
    await store.dispatch(endBreak());

    expect(attendanceService.endBreak).toHaveBeenCalledWith({
      latitude: POSITION.latitude,
      longitude: POSITION.longitude,
      accuracy_meters: POSITION.accuracyMeters,
    });
  });

  it("surfaces the backend refusal when a break is attempted off site", async () => {
    (locationService.getCurrentPosition as jest.Mock).mockResolvedValue(POSITION);
    (attendanceService.endBreak as jest.Mock).mockRejectedValue(
      new AxiosError("rejected", undefined, undefined, undefined, {
        data: { detail: "location is outside every eligible geofence" },
      } as any),
    );

    const store = buildStore();
    await store.dispatch(endBreak());

    expect(store.getState().attendance.actionError).toBe(
      "location is outside every eligible geofence",
    );
  });
});
