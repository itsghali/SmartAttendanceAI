import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.geo import Coordinates, haversine_distance_meters, is_within_polygon
from app.models.employee import Employee
from app.models.geofence import GeofenceBoundaryType
from app.models.geofence_event import GeofenceEventType
from app.models.mixins import utcnow
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.break_period_repository import BreakPeriodRepository
from app.repositories.geofence_event_repository import GeofenceEventRepository
from app.repositories.geofence_repository import GeofenceRepository

logger = logging.getLogger("app.monitoring")


@dataclass(frozen=True)
class PingResult:
    # "no_active_checkin" | "not_monitored" | "geofence_removed" | "on_break" | "in_zone" | "exited"
    status: str
    event_fired: GeofenceEventType | None
    # The server's last_ping_seq after this call, or None when there's no
    # attendance context to sync against (no_active_checkin). A device whose
    # clock is behind the server's already-recorded seq would otherwise have
    # every subsequent ping silently dropped as a stale duplicate forever —
    # the client clamps its next ping_seq to max(local_epoch, next_seq + 1),
    # so skew self-heals within one ping interval instead of persisting.
    next_seq: int | None


class MonitoringService:
    def __init__(self, session: AsyncSession):
        self._attendance = AttendanceRepository(session)
        self._geofences = GeofenceRepository(session)
        self._events = GeofenceEventRepository(session)
        self._breaks = BreakPeriodRepository(session)
        self._settings = get_settings()

    async def record_ping(
        self,
        employee: Employee,
        latitude: float,
        longitude: float,
        accuracy_meters: float | None,
        ping_seq: int,
    ) -> PingResult:
        # The open session, not "today's record" — an employee may have worked
        # several chantiers already today, and a night shift's session belongs to
        # yesterday's date while still being the one being monitored. Locked:
        # two devices pinging near-simultaneously for the same employee must
        # not both read the same pre-update outside_streak and both
        # independently cross the exit debounce threshold — see
        # get_open_for_employee_locked's docstring.
        attendance = await self._attendance.get_open_for_employee_locked(employee.id)
        if attendance is None:
            # Stale ping from a mobile client that hasn't noticed checkout yet —
            # not an error, just a no-op (plan decision: dropped silently).
            logger.info("ping dropped: no open attendance for employee=%s", employee.id)
            return PingResult(status="no_active_checkin", event_fired=None, next_seq=None)

        if await self._breaks.get_open_for_attendance(attendance.id) is not None:
            # CNIL doctrine bars location tracking during legally-protected rest
            # time. The mobile client already stops sending pings on a break —
            # this is the server-side backstop for an old/buggy/tampered client
            # that sends one anyway. Nothing is persisted: no coordinates, no
            # ping_seq, no debounce state — a break-time ping leaves no trace.
            logger.info(
                "ping dropped: open break for attendance=%s (buggy/tampered client?)",
                attendance.id,
            )
            return PingResult(status="on_break", event_fired=None, next_seq=attendance.last_ping_seq)

        # Idempotency: a ping_seq at or below the last processed one is a
        # retry/duplicate — ignore it without touching debounce state.
        if attendance.last_ping_seq is not None and ping_seq <= attendance.last_ping_seq:
            return PingResult(
                status=await self._current_status(attendance.id),
                event_fired=None,
                next_seq=attendance.last_ping_seq,
            )

        if attendance.check_in_geofence_id is None:
            # Manual/backfilled entries have no geofence to monitor against.
            await self._attendance.record_ping(attendance, ping_seq, utcnow(), attendance.outside_streak)
            return PingResult(status="not_monitored", event_fired=None, next_seq=attendance.last_ping_seq)

        if accuracy_meters is not None and accuracy_meters > self._settings.attendance_max_accuracy_meters:
            # Too imprecise to trust either way — record the ping so retries
            # of this same reading are still deduped, but don't move the
            # debounce counter in either direction.
            logger.info(
                "ping ignored: accuracy %.1fm exceeds %.1fm for attendance=%s",
                accuracy_meters,
                self._settings.attendance_max_accuracy_meters,
                attendance.id,
            )
            await self._attendance.record_ping(attendance, ping_seq, utcnow(), attendance.outside_streak)
            return PingResult(
                status=await self._current_status(attendance.id),
                event_fired=None,
                next_seq=attendance.last_ping_seq,
            )

        geofence = await self._geofences.get_by_id(attendance.check_in_geofence_id)
        if geofence is None:
            # Geofence was deleted mid-shift — stop monitoring silently.
            logger.warning(
                "monitoring stopped: geofence=%s deleted mid-shift for attendance=%s",
                attendance.check_in_geofence_id,
                attendance.id,
            )
            await self._attendance.record_ping(attendance, ping_seq, utcnow(), 0)
            return PingResult(status="geofence_removed", event_fired=None, next_seq=attendance.last_ping_seq)

        position = Coordinates(latitude, longitude)
        if geofence.boundary_type == GeofenceBoundaryType.POLYGON:
            points = [Coordinates(p["latitude"], p["longitude"]) for p in geofence.polygon_points]
            inside = is_within_polygon(position, points)
        else:
            distance = haversine_distance_meters(
                position, Coordinates(geofence.center_latitude, geofence.center_longitude)
            )
            inside = distance <= geofence.radius_meters
        currently_exited = await self._is_currently_exited(attendance.id)

        event_fired: GeofenceEventType | None = None
        new_streak = attendance.outside_streak
        if inside:
            new_streak = 0
            if currently_exited:
                await self._events.create(
                    employee.id, attendance.id, geofence.id, GeofenceEventType.RETURN, latitude, longitude
                )
                event_fired = GeofenceEventType.RETURN
        else:
            new_streak = attendance.outside_streak + 1
            if new_streak >= self._settings.geofence_exit_debounce_count and not currently_exited:
                await self._events.create(
                    employee.id, attendance.id, geofence.id, GeofenceEventType.EXIT, latitude, longitude
                )
                event_fired = GeofenceEventType.EXIT

        await self._attendance.record_ping(attendance, ping_seq, utcnow(), new_streak)

        still_exited = event_fired == GeofenceEventType.EXIT or (currently_exited and event_fired is None)
        return PingResult(
            status="exited" if still_exited else "in_zone",
            event_fired=event_fired,
            next_seq=attendance.last_ping_seq,
        )

    async def _is_currently_exited(self, attendance_id: uuid.UUID) -> bool:
        latest = await self._events.get_latest_for_attendance(attendance_id)
        return latest is not None and latest.event_type == GeofenceEventType.EXIT

    async def _current_status(self, attendance_id: uuid.UUID) -> str:
        return "exited" if await self._is_currently_exited(attendance_id) else "in_zone"
