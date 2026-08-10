import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.attendance import AttendanceStatus
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
