import { sendLocationPing } from "./attendanceService";
import type { LocationPingResult } from "./attendanceService";
import { getCurrentPosition } from "./locationService";

// Must match backend `geofence_ping_interval_seconds` (see PLAN.md Eng review
// Section 1 finding 6 — the interval is a fixed, coordinated constant, not
// something either side infers from the other).
const PING_INTERVAL_MS = 60_000;

// Pings are best-effort background work — a failed ping (permission revoked
// mid-shift, transient network error) should never surface as a user-facing
// error; it just skips that interval and tries again next tick.
export class GeofenceMonitor {
  private intervalId: ReturnType<typeof setInterval> | null = null;
  // Floor for the next ping_seq, learned from the server's `next_seq` on each
  // response. Epoch seconds alone survive an app restart (see the ping_seq
  // comment below) but not a device clock that's simply behind the server's
  // already-recorded value — a cheap construction-site Android phone with no
  // NTP sync is a realistic case. Without this floor, every ping from that
  // device would be silently dropped as a stale duplicate forever. With it,
  // the very next ping response reports the server's real last_ping_seq, so
  // skew self-heals within one interval instead of persisting.
  private seqFloor = 0;

  start(onResult: (result: LocationPingResult) => void): void {
    if (this.intervalId !== null) {
      return;
    }
    this.seqFloor = 0;
    this.intervalId = setInterval(() => {
      void this.tick(onResult);
    }, PING_INTERVAL_MS);
  }

  stop(): void {
    if (this.intervalId !== null) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  private async tick(onResult: (result: LocationPingResult) => void): Promise<void> {
    try {
      const position = await getCurrentPosition();
      // Wall-clock, not a bare incrementing counter: a counter resets to 0
      // every time this class is re-instantiated (app restart, screen
      // remount), which drops it behind the server's `last_ping_seq` from
      // earlier in the same shift. Epoch seconds survive that on their own —
      // real time only moves forward — but not a device clock that's behind
      // the server's, which `seqFloor` (updated from each response) corrects
      // for. Caveat: Postgres `last_ping_seq` is a 32-bit int, which epoch
      // seconds overflow in 2038 — fine for now, revisit well before then.
      const pingSeq = Math.max(Math.floor(Date.now() / 1000), this.seqFloor + 1);
      const result = await sendLocationPing({
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy_meters: position.accuracyMeters,
        ping_seq: pingSeq,
      });
      if (result.next_seq !== null) {
        this.seqFloor = result.next_seq;
      }
      onResult(result);
    } catch {
      // Best-effort — see class doc comment.
    }
  }
}
