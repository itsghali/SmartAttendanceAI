import * as Location from "expo-location";
import { Platform } from "react-native";

export interface CurrentPosition {
  latitude: number;
  longitude: number;
  accuracyMeters: number | null;
  // Android-only (expo-location's `mocked` field, undefined on iOS/web —
  // treated as false there, not as "unknown"). A weak, client-spoofable
  // signal on its own; the backend still enforces on it server-side (see
  // PLAN.md T1) so a modified UI alone can't bypass the check.
  isMocked: boolean;
}

export class LocationPermissionDeniedError extends Error {
  constructor() {
    super("location access is blocked. Allow location for this app, then try again.");
  }
}

export class LocationUnavailableError extends Error {
  constructor(reason: string) {
    super(`could not get your location: ${reason}`);
  }
}

/**
 * `getCurrentPositionAsync` has no timeout option (see the v57 LocationOptions:
 * accuracy / timeInterval / distanceInterval / mayShowUserSettingsDialog only),
 * and on desktop Chrome the Wi-Fi/IP provider can stall indefinitely instead of
 * rejecting. Without this cap a check-in tap spins forever and the 60 s geofence
 * ping tick piles up overlapping requests.
 */
const POSITION_TIMEOUT_MS = 15_000;

/**
 * A fix older than this is treated as unusable. Exit monitoring exists to prove
 * where the employee is *now*; a cached fix from before they left the site would
 * mask the exact event the module was built to catch. Deliberately above the
 * 60 s ping interval so a normal tick never trips it.
 */
const MAX_FIX_AGE_MS = 120_000;

// Browser geolocation (and expo-location's web shim over it) can reject with
// a raw GeolocationPositionError-shaped object rather than an Error instance
// — that object is not `instanceof Error`, so it silently fell through to a
// generic "something went wrong" in extractErrorMessage(). Normalize here so
// callers always see the real reason (timeout, position unavailable, etc).
function readErrorCode(error: unknown): number | null {
  if (typeof error === "object" && error !== null && "code" in error) {
    const code = (error as { code: unknown }).code;
    if (typeof code === "number") {
      return code;
    }
  }
  return null;
}

/**
 * Is this failure a permission refusal, on any platform?
 *
 * The web rejects with a numeric GeolocationPositionError code (1 ===
 * PERMISSION_DENIED). The native module does not: it throws an expo-modules-core
 * error whose `code` is a string and whose message reads "Calling the
 * 'getCurrentPositionAsync' function has failed → Caused by: Location permission
 * is required to do this operation." Matching only the numeric code silently
 * misfiled every native denial as a generic failure, so the app never asked for
 * permission at all. Match all three shapes.
 */
function isPermissionError(error: unknown): boolean {
  if (readErrorCode(error) === 1) {
    return true;
  }
  if (typeof error === "object" && error !== null) {
    const code = (error as { code?: unknown }).code;
    if (typeof code === "string" && /permission/i.test(code)) {
      return true;
    }
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && /permission/i.test(message)) {
      return true;
    }
  }
  return false;
}

/**
 * Standard GeolocationPositionError codes: 1 PERMISSION_DENIED,
 * 2 POSITION_UNAVAILABLE, 3 TIMEOUT.
 *
 * The code is checked BEFORE the message, deliberately. The browser's own
 * message for code 1 is "User denied Geolocation", which is both developer
 * vocabulary and frequently a lie: on Windows the site permission can be
 * granted while the OS refuses every desktop app, and Chrome still reports
 * that as PERMISSION_DENIED. Showing the raw string tells the employee they
 * denied something they never saw a prompt for, and offers no way out.
 */
function describeLocationFailure(error: unknown): string {
  switch (readErrorCode(error)) {
    case 1:
      return "location access is blocked. Allow location for this app, then try again.";
    case 2:
      return "no location signal. Step outside if you can, then try again.";
    case 3:
      return "timed out waiting for a location fix. Try again.";
  }
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  if (typeof error === "object" && error !== null && "message" in error) {
    const message = (error as { message: unknown }).message;
    if (typeof message === "string" && message.length > 0) {
      return message;
    }
  }
  return "unknown error";
}

/**
 * Dev-only diagnostic for the denial case, which is the one that looks like an
 * app bug and isn't.
 *
 * There are two distinct causes with the same symptom, and they need opposite
 * fixes, so this reads the actual browser permission state instead of asserting
 * one of them:
 *
 *   - state "denied"  — the *site* permission is blocked for this origin. No
 *     prompt will ever appear again for it. Fixed in Chrome's site settings.
 *   - state "granted" — the site is allowed and the refusal came from below the
 *     browser: on Windows, the OS-level location switch or the per-app consent
 *     for chrome.exe. No amount of in-app permission handling can fix that one.
 *
 * `expo-location`'s web shim resolves permission through
 * `navigator.permissions.query`, so a granted site permission is reported as
 * granted and the failure only surfaces later, at the position call.
 */
async function warnAboutBlockedLocation(): Promise<void> {
  if (!__DEV__) {
    return;
  }

  let state = "unknown";
  try {
    if (typeof navigator !== "undefined" && navigator.permissions?.query) {
      state = (await navigator.permissions.query({ name: "geolocation" as PermissionName })).state;
    } else {
      state = "not-a-browser";
    }
  } catch {
    state = "query-failed";
  }

  const cause =
    state === "denied"
      ? "  Cause: this SITE is blocked. Chrome will never prompt for it again.\n" +
        "  Fix: click the icon left of the URL > Location > Allow. Or chrome://settings/content/location,\n" +
        "    remove this origin from 'Not allowed to see your location'. Then hard-reload.\n"
      : state === "granted"
        ? "  Cause: the site IS allowed, so the refusal is coming from below the browser.\n" +
          "  Fix (Windows): Settings > Privacy & security > Location — turn on both 'Location services'\n" +
          "    and 'Let desktop apps access your location', then fully quit and reopen Chrome.\n"
        : "  Cause: could not read the permission state, so the layer refusing is unknown.\n" +
          "  Check both Chrome's site permission and Windows > Privacy & security > Location.\n";

  console.error(
    `[locationService] Location is BLOCKED (PERMISSION_DENIED). navigator.permissions state: ${state}\n` +
      cause +
      "  Note: desktop Chrome has no GPS radio — it resolves position from Wi-Fi/IP, typically\n" +
      "    1-5 km accuracy, which is above attendance_max_accuracy_meters (100 m) server-side.\n" +
      "    So even once unblocked, a real check-in will still be refused for accuracy.\n" +
      "    For real GPS use the Android emulator or a device development build.",
  );
}

/**
 * Dev-only GPS override, read from EXPO_PUBLIC_DEV_LOCATION="lat,lng".
 *
 * SECURITY — the `__DEV__` gate below is load-bearing, do not remove it.
 * This app gates attendance on physical presence; a location override is
 * exactly the bypass a fraud attempt would want. `__DEV__` is compiled to
 * false in release builds, so this branch cannot execute in a shipped app
 * even if the env var is somehow set. Never replace it with a runtime-only
 * check (a settings flag, a header, an env var alone) — those all survive
 * into production.
 *
 * Exists because OS-level geolocation is blocked on some dev machines
 * (Windows per-app location consent, browsers without a location provider),
 * which otherwise makes the check-in flow untestable locally.
 */
function isDevLocationOverrideEnabled(): boolean {
  return process.env.EXPO_PUBLIC_ALLOW_DEV_LOCATION_OVERRIDE === "true";
}

function readDevLocationOverride(): CurrentPosition | null {
  if (!__DEV__ || !isDevLocationOverrideEnabled()) {
    return null;
  }
  const raw = process.env.EXPO_PUBLIC_DEV_LOCATION;
  if (!raw) {
    return null;
  }
  const [latRaw, lngRaw] = raw.split(",");
  const latitude = Number(latRaw);
  const longitude = Number(lngRaw);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    console.warn(`[locationService] ignoring malformed EXPO_PUBLIC_DEV_LOCATION: ${raw}`);
    return null;
  }
  // Loud on purpose — a silent location override is how a dev convenience
  // turns into "why did prod accept a check-in from the wrong site".
  console.warn(
    `[locationService] DEV LOCATION OVERRIDE ACTIVE: ${latitude}, ${longitude} — real GPS is not being used.`,
  );
  return { latitude, longitude, accuracyMeters: 10, isMocked: false };
}

/**
 * One live fix, never a cached one. `getLastKnownPositionAsync` is deliberately
 * not used anywhere in this module — see MAX_FIX_AGE_MS.
 */
async function readLivePosition(): Promise<Location.LocationObject> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High }),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject({ code: 3, message: "position request timed out" }), POSITION_TIMEOUT_MS);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Native platforms only: get permission BEFORE asking for a position.
 *
 * This is the one place where native and web genuinely differ, and conflating
 * them is what broke iOS. In a browser, calling for a position is itself what
 * raises the prompt, so asking first is redundant and — on desktop Chrome, which
 * prompts once per origin and never again — actively misleading. On iOS and
 * Android the native module never prompts implicitly: without a granted
 * permission `getCurrentPositionAsync` simply throws "Location permission is
 * required to do this operation", and no amount of retrying changes that.
 */
async function ensureNativePermission(): Promise<void> {
  const current = await Location.getForegroundPermissionsAsync();
  if (current.status === "granted") {
    return;
  }
  if (!current.canAskAgain) {
    // Refused for good — the employee must re-enable it in system settings.
    throw new LocationPermissionDeniedError();
  }
  const requested = await Location.requestForegroundPermissionsAsync();
  if (requested.status !== "granted") {
    throw new LocationPermissionDeniedError();
  }
}

/**
 * Ask for permission only when the OS says a prompt can still appear.
 *
 * Returns true if it is worth retrying the position call.
 *
 * This is the whole reason the web flow below is position-first. Desktop Chrome
 * shows the location prompt once per origin and never again — a second
 * `requestForegroundPermissionsAsync()` resolves from the stored site setting
 * without a prompt, so "force a prompt until it works" is not a state the
 * browser can be driven into. Worse, that stored setting is not the same fact
 * as "coordinates are obtainable": on Windows the site permission can read
 * granted while the OS refuses every desktop app, and Chrome reports that as
 * PERMISSION_DENIED at the position call. The live fix is the only reliable
 * signal, so we take it first and consult permissions only to explain a failure.
 */
async function tryToUnblockPermission(): Promise<boolean> {
  const current = await Location.getForegroundPermissionsAsync();
  // Already granted, or the OS will not show a prompt again — a request call
  // here is a guaranteed no-op that just delays the error the caller needs.
  if (current.status === "granted" || current.canAskAgain === false) {
    return false;
  }
  const requested = await Location.requestForegroundPermissionsAsync();
  return requested.status === "granted";
}

function isStale(position: Location.LocationObject): boolean {
  if (typeof position.timestamp !== "number" || !Number.isFinite(position.timestamp)) {
    return false;
  }
  return Date.now() - position.timestamp > MAX_FIX_AGE_MS;
}

function toCurrentPosition(position: Location.LocationObject): CurrentPosition {
  if (isStale(position)) {
    throw new LocationUnavailableError("only an old location was available. Try again.");
  }
  return {
    latitude: position.coords.latitude,
    longitude: position.coords.longitude,
    // Null on web when the platform does not report it (v57 LocationObjectCoords).
    accuracyMeters: position.coords.accuracy ?? null,
    isMocked: position.mocked ?? false,
  };
}

export async function getCurrentPosition(): Promise<CurrentPosition> {
  const override = readDevLocationOverride();
  if (override) {
    return override;
  }

  // Native never prompts on its own, so the permission has to exist before the
  // position call. Web deliberately skips this — see ensureNativePermission().
  if (Platform.OS !== "web") {
    await ensureNativePermission();
  }

  try {
    return toCurrentPosition(await readLivePosition());
  } catch (error) {
    if (error instanceof LocationUnavailableError) {
      throw error;
    }
    if (!isPermissionError(error)) {
      throw new LocationUnavailableError(describeLocationFailure(error));
    }
    // A permission refusal — the only case where prompting can still change the
    // outcome, and only if the OS has not already made up its mind.
    if (!(await tryToUnblockPermission())) {
      await warnAboutBlockedLocation();
      throw new LocationPermissionDeniedError();
    }
    try {
      return toCurrentPosition(await readLivePosition());
    } catch (retryError) {
      if (retryError instanceof LocationUnavailableError) {
        throw retryError;
      }
      if (isPermissionError(retryError)) {
        await warnAboutBlockedLocation();
        throw new LocationPermissionDeniedError();
      }
      throw new LocationUnavailableError(describeLocationFailure(retryError));
    }
  }
}
