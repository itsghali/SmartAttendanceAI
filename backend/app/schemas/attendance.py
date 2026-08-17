import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.attendance import AttendanceStatus
from app.models.break_period import BreakSource
from app.models.geofence_event import GeofenceEventType


class CheckInRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0)
    # Base64-encoded selfie JPEG/PNG. Optional so this stays a pure additive
    # change — required only when FACE_VERIFICATION_ENABLED is on, enforced
    # in AttendanceService.check_in, not here (schema doesn't know settings).
    # max_length is a coarse parse-time ceiling (~11MB decoded) independent of
    # settings; the real cap against face_max_upload_size_mb is enforced in
    # AttendanceService._verify_face_or_raise before the image reaches the
    # face pipeline, mirroring face.py's multipart-upload validation.
    selfie_base64: str | None = Field(default=None, max_length=15_000_000)
    # Self-reported by the client (expo-location's Android-only `mocked`
    # flag) — only used on check-in, see PLAN.md T1. A weak, spoofable
    # signal on its own, still enforced server-side so a modified UI alone
    # can't bypass it.
    is_mock_location: bool = Field(default=False)
    # Self-reported by the client (deviceIntegrityService.ts's JS-level
    # heuristic, iOS only) — only used on check-in. Weaker than
    # is_mock_location, so this FLAGS the row for HR review rather than
    # blocking it (see check_in_is_jailbroken on the Attendance model).
    is_jailbroken: bool = Field(default=False)


class CheckOutRequest(CheckInRequest):
    pass


class BreakStartRequest(CheckInRequest):
    pass


class BreakEndRequest(CheckInRequest):
    pass


class LocationPingRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0)
    # Client-generated, monotonically increasing per check-in session. Backend
    # ignores any ping_seq at or below the last one it processed — this is the
    # idempotency mechanism for retried/duplicate pings (see PLAN.md Eng review).
    ping_seq: int = Field(ge=1)


class LocationPingResponse(BaseModel):
    # "no_active_checkin" | "not_monitored" | "geofence_removed" | "on_break" | "in_zone" | "exited"
    status: str
    event_fired: GeofenceEventType | None
    # Server's last_ping_seq after this call — lets the client clamp its next
    # ping_seq if its clock is behind the server's, instead of every
    # subsequent ping being silently dropped as a stale duplicate.
    next_seq: int | None


class BreakPeriodOut(BaseModel):
    id: uuid.UUID
    source: BreakSource
    break_start_at: datetime
    break_end_at: datetime | None

    start_latitude: float | None = None
    start_longitude: float | None = None
    start_accuracy_meters: float | None = None

    end_latitude: float | None = None
    end_longitude: float | None = None
    end_accuracy_meters: float | None = None

    model_config = {"from_attributes": True}


class GeofenceEventOut(BaseModel):
    id: uuid.UUID
    event_type: GeofenceEventType
    latitude: float
    longitude: float
    created_at: datetime

    model_config = {"from_attributes": True}


class AttendanceOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    attendance_date: date
    check_in_at: datetime
    check_in_latitude: float | None
    check_in_longitude: float | None
    check_in_accuracy_meters: float | None
    check_in_geofence_id: uuid.UUID | None
    check_out_at: datetime | None
    check_out_latitude: float | None
    check_out_longitude: float | None
    check_out_accuracy_meters: float | None
    check_out_geofence_id: uuid.UUID | None
    status: AttendanceStatus
    is_manual_entry: bool
    notes: str
    check_in_is_jailbroken: bool
    breaks: list[BreakPeriodOut]
    geofence_events: list[GeofenceEventOut]
    # "not_monitored" | "on_break" | "live" | "stale" | None (session closed).
    # Read-time derivation — see Attendance.monitoring_status.
    monitoring_status: str | None = None

    model_config = {"from_attributes": True}


class TodayAttendanceOut(BaseModel):
    """An employee's day, which may span several chantiers.

    `current` is the session open right now (null when checked out of everything)
    and is what the app drives its buttons off. `sessions` is every session that
    STARTED today — so a night shift still running from yesterday appears in
    `current` but not in `sessions`, which is intended: the list is the calendar
    day's work, the field is what is happening now.
    """

    current: AttendanceOut | None
    sessions: list[AttendanceOut]


class AttendanceListOut(BaseModel):
    items: list[AttendanceOut]
    total: int
    limit: int
    offset: int


class GeofenceEventSummaryOut(BaseModel):
    """Event-summary only — deliberately has no latitude/longitude fields.

    Codex outside-voice finding (2026-08-11, geofence-alerts eng review):
    AttendanceOut and GeofenceEventOut both still ship raw coordinates,
    which makes "event-summary only, no coordinates" (design doc premise #4)
    a frontend convention rather than a guarantee. This schema is the actual
    enforcement point — it has nothing to leak because the fields don't
    exist here, not because a caller remembers to hide them.
    """

    # str, not uuid.UUID: a check-in and its check-out share one Attendance
    # id, so the route synthesizes distinct string ids for those two merged
    # timeline entries ("{attendance_id}-checkin" / "-checkout") — a real
    # GeofenceEvent id stringifies fine into the same field.
    id: str
    # "enter" | "exit" | "return" (GeofenceEventType) | "check_in" | "check_out"
    # — widened from GeofenceEventType to str so the same row shape covers
    # the merged check-in/check-out timeline entries the route adds
    # alongside real geofence events (see get_employee_geofence_history).
    event_type: str
    # "Deleted geofence" when the source geofence was removed after the
    # event fired (geofence_id nulls out via ON DELETE SET NULL); "Not
    # monitored" when there was never a geofence to begin with — never
    # blank, per design doc success criteria.
    geofence_name: str
    created_at: datetime
    # Added for the Event Details drawer (autoplan geofence-monitoring
    # UI/UX review, 2026-08-11) — null when there's no source geofence to
    # read a radius from (deleted/not-monitored), same nullability pattern
    # as geofence_name's fallback labels.
    authorized_radius_meters: float | None = None
    # Populated only on event_type == "exit" rows, paired against the next
    # RETURN in the same attendance_id (see get_employee_geofence_history).
    # Both null on every other row type.
    duration_minutes: int | None = None
    still_open: bool | None = None


class GeofenceEventHistoryOut(BaseModel):
    items: list[GeofenceEventSummaryOut]
    total: int
    limit: int
    offset: int


class AttendanceExceptionOut(BaseModel):
    """One row on the "Site status — today" exceptions screen.

    No lat/lng, same rationale as GeofenceEventSummaryOut. Carries employee
    identity explicitly (Codex outside-voice finding: employee_id alone is
    unusable — HR has no way to know who a raw UUID refers to).
    """

    employee_id: uuid.UUID
    employee_full_name: str
    employee_code: str
    attendance_id: uuid.UUID
    check_in_at: datetime
    # "not_monitored" | "on_break" | "live" | "stale" — see
    # Attendance.monitoring_status. None only if check_out_at is set, which
    # should not happen for rows on this screen (exceptions query is
    # open-attendance-only), but the type follows the source property.
    monitoring_status: str | None
    # True when this attendance's latest geofence_events row is an EXIT
    # that hasn't been followed by a RETURN — the "needs attention" signal.
    needs_attention: bool
    # Added for the alert table's Event/Geofence/Detected At columns
    # (autoplan geofence-monitoring UI/UX review, 2026-08-11, Path B).
    # last_event_type/at come from the same geofence_events eager-load
    # already used to compute needs_attention above — no new query.
    # "enter" | "exit" | "return" | None (no geofence event yet, e.g. a
    # manual-entry check-in with no geofence assigned at all).
    last_event_type: str | None = None
    last_event_at: datetime | None = None
    # Current check-in geofence's name — "Deleted geofence" / "Not
    # monitored" fallback, same _geofence_label() convention used in the
    # history endpoint. Never blank.
    geofence_name: str | None = None


class AttendanceExceptionsListOut(BaseModel):
    items: list[AttendanceExceptionOut]
    needs_attention_count: int
    total: int


class ManualEntryRequest(BaseModel):
    attendance_date: date
    check_in_at: datetime
    check_out_at: datetime | None = None
    status: AttendanceStatus = AttendanceStatus.PRESENT
    notes: str = Field(default="", max_length=1000)


class AttendanceCorrection(BaseModel):
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    status: AttendanceStatus | None = None
    notes: str | None = Field(default=None, max_length=1000)
