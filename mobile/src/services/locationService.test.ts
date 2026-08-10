import * as Location from "expo-location";
import { Platform } from "react-native";

jest.mock("expo-location");

const ORIGINAL_ENV = process.env.EXPO_PUBLIC_DEV_LOCATION;
const ORIGINAL_ALLOW_DEV_LOCATION = process.env.EXPO_PUBLIC_ALLOW_DEV_LOCATION_OVERRIDE;
const ORIGINAL_PLATFORM = Platform.OS;

/**
 * Native and web take deliberately different paths through getCurrentPosition()
 * — native must hold a permission before asking for a position, web must not —
 * so every test that touches that split states which platform it means.
 */
function setPlatform(os: typeof Platform.OS) {
  Object.defineProperty(Platform, "OS", { value: os, configurable: true, writable: true });
}

function loadService() {
  // The override is read per-call, but the module reads __DEV__ at call time
  // too — re-require so each test sees the env/globals it just set.
  let mod: typeof import("./locationService");
  jest.isolateModules(() => {
    mod = require("./locationService");
  });
  return mod!;
}

function mockRealGps(latitude: number, longitude: number) {
  (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
    status: "granted",
    canAskAgain: false,
  });
  (Location.requestForegroundPermissionsAsync as jest.Mock).mockResolvedValue({ status: "granted" });
  (Location.getCurrentPositionAsync as jest.Mock).mockResolvedValue({
    coords: { latitude, longitude, accuracy: 5 },
    timestamp: Date.now(),
  });
}

/** A live fix, always freshly stamped. */
function fix(latitude: number, longitude: number, ageMs = 0) {
  return {
    coords: { latitude, longitude, accuracy: 5 },
    timestamp: Date.now() - ageMs,
  };
}

describe("locationService dev location override", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(console, "warn").mockImplementation(() => {});
    // getCurrentPosition() emits a dev-only console.error diagnostic on a blocked
    // location — expected output, not a test failure.
    jest.spyOn(console, "error").mockImplementation(() => {});
    (global as any).__DEV__ = true;
  });

  afterEach(() => {
    process.env.EXPO_PUBLIC_DEV_LOCATION = ORIGINAL_ENV;
    process.env.EXPO_PUBLIC_ALLOW_DEV_LOCATION_OVERRIDE = ORIGINAL_ALLOW_DEV_LOCATION;
    (global as any).__DEV__ = true;
    setPlatform(ORIGINAL_PLATFORM);
    jest.restoreAllMocks();
  });

  it("returns the override position in dev when the env var is set", async () => {
    process.env.EXPO_PUBLIC_ALLOW_DEV_LOCATION_OVERRIDE = "true";
    process.env.EXPO_PUBLIC_DEV_LOCATION = "33.5731,-7.5898";
    mockRealGps(1, 1);

    const position = await loadService().getCurrentPosition();

    expect(position).toEqual({ latitude: 33.5731, longitude: -7.5898, accuracyMeters: 10 });
    // Real GPS must not even be consulted when the override is active.
    expect(Location.getCurrentPositionAsync).not.toHaveBeenCalled();
  });

  it("SECURITY: ignores the override entirely when __DEV__ is false", async () => {
    process.env.EXPO_PUBLIC_ALLOW_DEV_LOCATION_OVERRIDE = "true";
    process.env.EXPO_PUBLIC_DEV_LOCATION = "33.5731,-7.5898";
    (global as any).__DEV__ = false;
    mockRealGps(36.8065, 10.1815);

    const position = await loadService().getCurrentPosition();

    // Production builds must use real GPS regardless of what the env says —
    // this is the gate that stops a location override becoming a fraud bypass.
    expect(position.latitude).toBe(36.8065);
    expect(position.longitude).toBe(10.1815);
    expect(Location.getCurrentPositionAsync).toHaveBeenCalled();
  });

  it("falls back to real GPS when the override is malformed", async () => {
    process.env.EXPO_PUBLIC_ALLOW_DEV_LOCATION_OVERRIDE = "true";
    process.env.EXPO_PUBLIC_DEV_LOCATION = "not-a-coordinate";
    mockRealGps(36.8065, 10.1815);

    const position = await loadService().getCurrentPosition();

    expect(position.latitude).toBe(36.8065);
    expect(Location.getCurrentPositionAsync).toHaveBeenCalled();
  });

  it("uses real GPS when no override is set", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    mockRealGps(36.8065, 10.1815);

    const position = await loadService().getCurrentPosition();

    expect(position.latitude).toBe(36.8065);
    expect(Location.getCurrentPositionAsync).toHaveBeenCalled();
  });

  it("WEB: reads live coordinates without asking for permission first", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    setPlatform("web");
    mockRealGps(36.8065, 10.1815);

    await loadService().getCurrentPosition();

    // Desktop Chrome prompts once per origin and never again, so a permission
    // request on the happy path buys nothing and hides the real signal — the fix.
    expect(Location.requestForegroundPermissionsAsync).not.toHaveBeenCalled();
    expect(Location.getCurrentPositionAsync).toHaveBeenCalled();
  });

  it("NATIVE: gets permission BEFORE asking for a position", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    setPlatform("ios");
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "undetermined",
      canAskAgain: true,
    });
    (Location.requestForegroundPermissionsAsync as jest.Mock).mockResolvedValue({ status: "granted" });
    (Location.getCurrentPositionAsync as jest.Mock).mockResolvedValue(fix(36.8065, 10.1815));

    const position = await loadService().getCurrentPosition();

    // The native module never prompts implicitly — without this the position call
    // just throws "Location permission is required" and iOS is never asked at all.
    expect(Location.requestForegroundPermissionsAsync).toHaveBeenCalled();
    expect(position.latitude).toBe(36.8065);
  });

  it("NATIVE: reports a blocked permission without calling for a position", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    setPlatform("ios");
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "denied",
      canAskAgain: false,
    });

    await expect(loadService().getCurrentPosition()).rejects.toThrow("location access is blocked");
    expect(Location.getCurrentPositionAsync).not.toHaveBeenCalled();
  });

  it("NATIVE: classifies the native permission error, which carries no numeric code", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    setPlatform("ios");
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });
    // The real shape thrown by expo-location on iOS: a string code and a message,
    // no numeric GeolocationPositionError code. Matching only `code === 1` filed
    // this as a generic failure and showed the employee the raw internal string.
    (Location.getCurrentPositionAsync as jest.Mock).mockRejectedValue({
      code: "ERR_LOCATION_PERMISSION_DENIED",
      message:
        "Calling the 'getCurrentPositionAsync' function has failed\n→ Caused by: Location permission is required to do this operation.",
    });

    const attempt = loadService().getCurrentPosition();
    await expect(attempt).rejects.toThrow("location access is blocked");
    await expect(attempt).rejects.not.toThrow(/getCurrentPositionAsync/);
  });

  it("WEB: prompts once and retries when permission is still promptable", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    setPlatform("web");
    (Location.getCurrentPositionAsync as jest.Mock)
      .mockRejectedValueOnce({ code: 1, message: "User denied Geolocation" })
      .mockResolvedValueOnce(fix(36.8065, 10.1815));
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "undetermined",
      canAskAgain: true,
    });
    (Location.requestForegroundPermissionsAsync as jest.Mock).mockResolvedValue({ status: "granted" });

    const position = await loadService().getCurrentPosition();

    expect(position.latitude).toBe(36.8065);
    expect(Location.requestForegroundPermissionsAsync).toHaveBeenCalledTimes(1);
    expect(Location.getCurrentPositionAsync).toHaveBeenCalledTimes(2);
  });

  it("does not re-request permission when the OS will not prompt again", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    // Chrome's site setting reads granted while Windows refuses desktop apps —
    // the position call is the only thing that knows, and no prompt can fix it.
    (Location.getCurrentPositionAsync as jest.Mock).mockRejectedValue({
      code: 1,
      message: "User denied Geolocation",
    });
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });

    // Matched on message, not class: loadService() uses jest.isolateModules, so the
    // re-required module defines a fresh class object that fails an instanceof check.
    await expect(loadService().getCurrentPosition()).rejects.toThrow("location access is blocked");
    expect(Location.requestForegroundPermissionsAsync).not.toHaveBeenCalled();
  });

  it("surfaces a named error when a granted prompt still yields no fix", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    (Location.getCurrentPositionAsync as jest.Mock).mockRejectedValue({
      code: 1,
      message: "User denied Geolocation",
    });
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "undetermined",
      canAskAgain: true,
    });
    (Location.requestForegroundPermissionsAsync as jest.Mock).mockResolvedValue({ status: "denied" });

    await expect(loadService().getCurrentPosition()).rejects.toThrow("location access is blocked");
  });

  it("never shows the browser's raw 'User denied Geolocation' string", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });
    (Location.getCurrentPositionAsync as jest.Mock).mockRejectedValue({
      code: 1,
      message: "User denied Geolocation",
    });

    // The employee never saw a prompt to deny — the OS refused. Telling them they
    // denied it is both false and unactionable.
    await expect(loadService().getCurrentPosition()).rejects.not.toThrow(/User denied/);
  });

  it("rejects a stale fix instead of reporting an old position as live", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    mockRealGps(36.8065, 10.1815);
    (Location.getCurrentPositionAsync as jest.Mock).mockResolvedValue(fix(36.8065, 10.1815, 300_000));

    // A cached fix from before the employee left the site would mask the exit
    // that geofence monitoring exists to catch.
    await expect(loadService().getCurrentPosition()).rejects.toThrow("only an old location");
  });

  it("accepts a null accuracy, which web reports when it has none", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });
    (Location.getCurrentPositionAsync as jest.Mock).mockResolvedValue({
      coords: { latitude: 36.8065, longitude: 10.1815, accuracy: null },
      timestamp: Date.now(),
    });

    await expect(loadService().getCurrentPosition()).resolves.toEqual({
      latitude: 36.8065,
      longitude: 10.1815,
      accuracyMeters: null,
    });
  });

  it("maps POSITION_UNAVAILABLE and TIMEOUT to actionable copy", async () => {
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });

    (Location.getCurrentPositionAsync as jest.Mock).mockRejectedValue({ code: 2, message: "raw" });
    await expect(loadService().getCurrentPosition()).rejects.toThrow("no location signal");

    (Location.getCurrentPositionAsync as jest.Mock).mockRejectedValue({ code: 3, message: "raw" });
    await expect(loadService().getCurrentPosition()).rejects.toThrow("timed out");
  });

  it("times out a position call that never settles", async () => {
    jest.useFakeTimers();
    delete process.env.EXPO_PUBLIC_DEV_LOCATION;
    (Location.getForegroundPermissionsAsync as jest.Mock).mockResolvedValue({
      status: "granted",
      canAskAgain: false,
    });
    // Desktop Chrome's Wi-Fi/IP provider can stall forever instead of rejecting.
    (Location.getCurrentPositionAsync as jest.Mock).mockReturnValue(new Promise(() => {}));

    const pending = loadService().getCurrentPosition();
    const assertion = expect(pending).rejects.toThrow("timed out");
    // Async form: the native permission check awaits before readLivePosition()
    // schedules the timer, so a synchronous advance would fire against nothing.
    await jest.advanceTimersByTimeAsync(15_000);
    await assertion;
    jest.useRealTimers();
  });
});
