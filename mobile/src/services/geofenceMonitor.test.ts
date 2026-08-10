import { GeofenceMonitor } from "./geofenceMonitor";
import { sendLocationPing } from "./attendanceService";
import { getCurrentPosition } from "./locationService";

jest.mock("./attendanceService");
jest.mock("./locationService");

const PING_INTERVAL_MS = 60_000;

describe("GeofenceMonitor ping_seq", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-01-01T00:00:00.000Z"));
    (getCurrentPosition as jest.Mock).mockResolvedValue({
      latitude: 36.8065,
      longitude: 10.1815,
      accuracyMeters: 5,
    });
    (sendLocationPing as jest.Mock).mockResolvedValue({
      status: "in_zone",
      event_fired: null,
      next_seq: null,
    });
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.clearAllMocks();
  });

  // The bug: a fresh instance previously reset its counter to 0, so a ping
  // sent after an app restart mid-shift carried a LOWER ping_seq than the
  // server's `last_ping_seq` from before the restart — the backend's
  // idempotency check (`ping_seq <= last_ping_seq`) then silently dropped
  // every subsequent ping as a stale duplicate.
  it("a fresh instance after a restart sends a ping_seq higher than the prior instance's last ping", async () => {
    const first = new GeofenceMonitor();
    first.start(() => {});
    await jest.advanceTimersByTimeAsync(PING_INTERVAL_MS);
    first.stop();

    const firstSeq = (sendLocationPing as jest.Mock).mock.calls[0][0].ping_seq;

    jest.setSystemTime(new Date("2026-01-01T00:05:00.000Z")); // app restarted 5 min later
    const second = new GeofenceMonitor();
    second.start(() => {});
    await jest.advanceTimersByTimeAsync(PING_INTERVAL_MS);
    second.stop();

    const secondSeq = (sendLocationPing as jest.Mock).mock.calls[1][0].ping_seq;

    expect(secondSeq).toBeGreaterThan(firstSeq);
  });

  it("sends ping_seq as whole-second epoch time", async () => {
    const monitor = new GeofenceMonitor();
    monitor.start(() => {});
    await jest.advanceTimersByTimeAsync(PING_INTERVAL_MS);
    monitor.stop();

    const seq = (sendLocationPing as jest.Mock).mock.calls[0][0].ping_seq;
    expect(seq).toBe(Math.floor(new Date("2026-01-01T00:01:00.000Z").getTime() / 1000));
  });

  // A device whose clock is behind the server's already-recorded last_ping_seq
  // (e.g. no NTP sync) would otherwise have every ping dropped as a stale
  // duplicate forever — the server-reported `next_seq` on each response must
  // raise the floor so skew self-heals instead of persisting.
  it("clamps ping_seq above a server-reported next_seq that exceeds the device clock", async () => {
    const farFutureServerSeq = Math.floor(new Date("2026-01-01T00:00:00.000Z").getTime() / 1000) + 10_000;
    (sendLocationPing as jest.Mock)
      .mockResolvedValueOnce({ status: "exited", event_fired: "exit", next_seq: farFutureServerSeq })
      .mockResolvedValueOnce({ status: "in_zone", event_fired: null, next_seq: null });

    const monitor = new GeofenceMonitor();
    monitor.start(() => {});
    await jest.advanceTimersByTimeAsync(PING_INTERVAL_MS);
    await jest.advanceTimersByTimeAsync(PING_INTERVAL_MS);
    monitor.stop();

    const secondSeq = (sendLocationPing as jest.Mock).mock.calls[1][0].ping_seq;
    expect(secondSeq).toBeGreaterThan(farFutureServerSeq);
  });

  it("does not lower the floor when next_seq is null (no active attendance to sync against)", async () => {
    const monitor = new GeofenceMonitor();
    monitor.start(() => {});
    await jest.advanceTimersByTimeAsync(PING_INTERVAL_MS);
    monitor.stop();

    const seq = (sendLocationPing as jest.Mock).mock.calls[0][0].ping_seq;
    expect(seq).toBe(Math.floor(new Date("2026-01-01T00:01:00.000Z").getTime() / 1000));
  });
});
