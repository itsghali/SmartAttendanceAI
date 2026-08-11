import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.core.exceptions import (
    AlreadyCheckedInError,
    AlreadyCheckedOutError,
    BreakAlreadyActiveError,
    BreakStillActiveError,
    EmployeeNotFoundError,
    FaceMismatchError,
    FaceModelUnavailableError,
    FaceProfileCorruptedError,
    FaceProfileNotFoundError,
    ImpossibleTravelError,
    InvalidImageError,
    LivenessCheckFailedError,
    MockLocationDetectedError,
    MultipleFacesDetectedError,
    NoActiveBreakError,
    NoActiveGeofenceError,
    NoFaceDetectedError,
    NotCheckedInError,
    OutsideGeofenceError,
    PoorLocationAccuracyError,
)
from app.core.rate_limit import RateLimiter, get_redis_client
from app.models.geofence import Geofence
from app.models.geofence_event import GeofenceEventType
from app.models.user import User
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.geofence_event_repository import GeofenceEventRepository
from app.schemas.attendance import (
    AttendanceCorrection,
    AttendanceExceptionOut,
    AttendanceExceptionsListOut,
    AttendanceListOut,
    AttendanceOut,
    BreakEndRequest,
    BreakPeriodOut,
    BreakStartRequest,
    CheckInRequest,
    CheckOutRequest,
    GeofenceEventHistoryOut,
    GeofenceEventSummaryOut,
    LocationPingRequest,
    LocationPingResponse,
    ManualEntryRequest,
    TodayAttendanceOut,
)
from app.services.attendance_service import AttendanceService
from app.services.employee_service import EmployeeService
from app.services.monitoring_service import MonitoringService

router = APIRouter(prefix="/attendance", tags=["attendance"])

_CONFLICT_ERRORS = (
    AlreadyCheckedInError,
    AlreadyCheckedOutError,
    BreakAlreadyActiveError,
    NoActiveBreakError,
    NotCheckedInError,
    BreakStillActiveError,
)
_BAD_REQUEST_ERRORS = (
    OutsideGeofenceError,
    PoorLocationAccuracyError,
    NoActiveGeofenceError,
    MockLocationDetectedError,
    ImpossibleTravelError,
)
# A rejected check-in/check-out/break action is a request failure here,
# unlike the standalone /face/verify endpoint (which answers 200
# {verified:false} because a face mismatch there isn't gating anything else)
# — each of these actions IS the gate.
_FACE_ACTION_ERRORS = (
    InvalidImageError,
    NoFaceDetectedError,
    MultipleFacesDetectedError,
    FaceMismatchError,
    LivenessCheckFailedError,
    FaceProfileNotFoundError,
)


async def _resolve_employee(user: User, session: AsyncSession):
    employee = await EmployeeService(session).get_by_user_id(user.id)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no employee profile for this account"
        )
    return employee


async def _location_ping_rate_limit(
    user: User = Depends(get_current_user), redis: Redis = Depends(get_redis_client)
) -> None:
    # Keyed on the authenticated user, not client IP — pings from one employee's
    # device shouldn't be able to starve another's quota, and IP is unreliable
    # for mobile clients anyway (see PLAN.md Eng review Section 1 finding 5).
    settings = get_settings()
    limiter = RateLimiter(
        redis,
        "location-ping",
        settings.location_ping_rate_limit_per_window,
        settings.location_ping_rate_limit_window_seconds,
    )
    await limiter.check(str(user.id))


async def _attendance_action_rate_limit(
    user: User = Depends(get_current_user), redis: Redis = Depends(get_redis_client)
) -> None:
    # Same per-user keying rationale as _location_ping_rate_limit above.
    settings = get_settings()
    limiter = RateLimiter(
        redis,
        "attendance-action",
        settings.attendance_action_rate_limit_per_window,
        settings.attendance_action_rate_limit_window_seconds,
    )
    await limiter.check(str(user.id))


@router.post(
    "/check-in",
    response_model=AttendanceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permission("attendance:record:own")),
        Depends(_attendance_action_rate_limit),
    ],
)
async def check_in(
    body: CheckInRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AttendanceOut:
    employee = await _resolve_employee(user, session)
    try:
        attendance = await AttendanceService(session).check_in(
            employee,
            body.latitude,
            body.longitude,
            body.accuracy_meters,
            body.selfie_base64,
            body.is_mock_location,
            body.is_jailbroken,
        )
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (FaceModelUnavailableError, FaceProfileCorruptedError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (*_BAD_REQUEST_ERRORS, *_FACE_ACTION_ERRORS) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AttendanceOut.model_validate(attendance)


@router.post(
    "/check-out",
    response_model=AttendanceOut,
    dependencies=[
        Depends(require_permission("attendance:record:own")),
        Depends(_attendance_action_rate_limit),
    ],
)
async def check_out(
    body: CheckOutRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AttendanceOut:
    employee = await _resolve_employee(user, session)
    try:
        attendance = await AttendanceService(session).check_out(
            employee, body.latitude, body.longitude, body.accuracy_meters, body.selfie_base64
        )
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (FaceModelUnavailableError, FaceProfileCorruptedError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (*_BAD_REQUEST_ERRORS, *_FACE_ACTION_ERRORS) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AttendanceOut.model_validate(attendance)


@router.post(
    "/location-ping",
    response_model=LocationPingResponse,
    dependencies=[
        Depends(require_permission("attendance:record:own")),
        Depends(_location_ping_rate_limit),
    ],
)
async def location_ping(
    body: LocationPingRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> LocationPingResponse:
    employee = await _resolve_employee(user, session)
    result = await MonitoringService(session).record_ping(
        employee, body.latitude, body.longitude, body.accuracy_meters, body.ping_seq
    )
    return LocationPingResponse(
        status=result.status, event_fired=result.event_fired, next_seq=result.next_seq
    )


@router.post(
    "/break/start",
    response_model=BreakPeriodOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permission("attendance:record:own")),
        Depends(_attendance_action_rate_limit),
    ],
)
async def start_break(
    body: BreakStartRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> BreakPeriodOut:
    employee = await _resolve_employee(user, session)
    try:
        break_period = await AttendanceService(session).start_break(
            employee, body.latitude, body.longitude, body.accuracy_meters, body.selfie_base64
        )
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (FaceModelUnavailableError, FaceProfileCorruptedError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (*_BAD_REQUEST_ERRORS, *_FACE_ACTION_ERRORS) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BreakPeriodOut.model_validate(break_period)


@router.post(
    "/break/end",
    response_model=BreakPeriodOut,
    dependencies=[
        Depends(require_permission("attendance:record:own")),
        Depends(_attendance_action_rate_limit),
    ],
)
async def end_break(
    body: BreakEndRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> BreakPeriodOut:
    employee = await _resolve_employee(user, session)
    try:
        break_period = await AttendanceService(session).end_break(
            employee, body.latitude, body.longitude, body.accuracy_meters, body.selfie_base64
        )
    except _CONFLICT_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (FaceModelUnavailableError, FaceProfileCorruptedError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (*_BAD_REQUEST_ERRORS, *_FACE_ACTION_ERRORS) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BreakPeriodOut.model_validate(break_period)


@router.get(
    "/me/today",
    response_model=TodayAttendanceOut,
    dependencies=[Depends(require_permission("attendance:read:own"))],
)
async def get_my_attendance_today(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
) -> TodayAttendanceOut:
    employee = await _resolve_employee(user, session)
    current, sessions = await AttendanceService(session).get_today(employee.id)
    return TodayAttendanceOut(
        current=AttendanceOut.model_validate(current) if current else None,
        sessions=[AttendanceOut.model_validate(s) for s in sessions],
    )


@router.get(
    "/me",
    response_model=AttendanceListOut,
    dependencies=[Depends(require_permission("attendance:read:own"))],
)
async def list_my_attendance(
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AttendanceListOut:
    employee = await _resolve_employee(user, session)
    records, total = await AttendanceService(session).list_for_employee(
        employee.id, date_from, date_to, limit, offset
    )
    return AttendanceListOut(
        items=[AttendanceOut.model_validate(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "",
    response_model=AttendanceListOut,
)
async def list_all_attendance(
    employee_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_permission("attendance:read:all")),
    session: AsyncSession = Depends(get_db),
) -> AttendanceListOut:
    # "attendance:read:all" spans supervisor up through super_admin — a
    # supervisor is scoped to their own department, everyone above that
    # sees the whole company. A requested department_id outside a
    # supervisor's own is rejected rather than silently overridden, so the
    # caller isn't misled into thinking they saw another department's data.
    if user.role.name == "supervisor":
        own_employee = await _resolve_employee(user, session)
        if department_id is not None and department_id != own_employee.department_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="supervisors may only view their own department",
            )
        department_id = own_employee.department_id

    records, total = await AttendanceService(session).list_all(
        employee_id, department_id, date_from, date_to, limit, offset
    )
    return AttendanceListOut(
        items=[AttendanceOut.model_validate(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/exceptions",
    response_model=AttendanceExceptionsListOut,
    dependencies=[Depends(require_permission("geofence_events:read"))],
)
async def list_attendance_exceptions(
    session: AsyncSession = Depends(get_db),
) -> AttendanceExceptionsListOut:
    # Registered before /{attendance_id} deliberately — FastAPI/Starlette
    # matches routes in registration order, and a literal "/exceptions"
    # segment would otherwise be swallowed by the {attendance_id} path param.
    records = await AttendanceRepository(session).list_open()
    items = []
    needs_attention_count = 0
    for record in records:
        latest_event = record.geofence_events[-1] if record.geofence_events else None
        needs_attention = latest_event is not None and latest_event.event_type == GeofenceEventType.EXIT
        if needs_attention:
            needs_attention_count += 1
        items.append(
            AttendanceExceptionOut(
                employee_id=record.employee_id,
                employee_full_name=record.employee.user.full_name,
                employee_code=record.employee.employee_code,
                attendance_id=record.id,
                check_in_at=record.check_in_at,
                monitoring_status=record.monitoring_status,
                needs_attention=needs_attention,
            )
        )
    return AttendanceExceptionsListOut(
        items=items, needs_attention_count=needs_attention_count, total=len(items)
    )


def _geofence_label(geofence: Geofence | None, is_manual_entry: bool) -> str:
    # A normal self-service check-in always requires an active geofence
    # match (NoActiveGeofenceError otherwise) — same for the geofence_events
    # that fire during monitoring (MonitoringService never creates one with
    # a null geofence_id). So for those, a null geofence now unambiguously
    # means it existed and was later deleted. Manual/backfilled entries are
    # the one path that can start with no geofence at all — that's
    # "not monitored" from the beginning, not a deletion.
    if geofence is not None:
        return geofence.name
    return "Not monitored" if is_manual_entry else "Deleted geofence"


@router.get(
    "/{employee_id}/history",
    response_model=GeofenceEventHistoryOut,
    dependencies=[Depends(require_permission("geofence_events:read"))],
)
async def get_employee_geofence_history(
    employee_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    event_type: GeofenceEventType | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> GeofenceEventHistoryOut:
    events = await GeofenceEventRepository(session).list_all_for_employee(
        employee_id, date_from, date_to, event_type
    )
    entries = [
        GeofenceEventSummaryOut(
            id=str(event.id),
            event_type=event.event_type.value,
            geofence_name=_geofence_label(event.geofence, is_manual_entry=False),
            created_at=event.created_at,
        )
        for event in events
    ]

    # Merge in check-in/check-out — not a geofence_events row, but the same
    # timeline HR reads to resolve a payroll dispute. Only merged when the
    # event_type filter isn't narrowing to a real geofence-event type, since
    # check_in/check_out aren't ENTER/EXIT/RETURN and a filtered request is
    # explicitly asking for geofence events only.
    if event_type is None:
        sessions = await AttendanceRepository(session).list_all_for_employee(
            employee_id, date_from, date_to
        )
        for attendance in sessions:
            entries.append(
                GeofenceEventSummaryOut(
                    id=f"{attendance.id}-checkin",
                    event_type="check_in",
                    geofence_name=_geofence_label(
                        attendance.check_in_geofence, attendance.is_manual_entry
                    ),
                    created_at=attendance.check_in_at,
                )
            )
            if attendance.check_out_at is not None:
                entries.append(
                    GeofenceEventSummaryOut(
                        id=f"{attendance.id}-checkout",
                        event_type="check_out",
                        geofence_name=_geofence_label(
                            attendance.check_out_geofence, attendance.is_manual_entry
                        ),
                        created_at=attendance.check_out_at,
                    )
                )

    # Merged across two tables, so pagination happens here rather than in
    # SQL — a single LIMIT/OFFSET can't paginate correctly across both.
    # Bounded by realistic per-employee volume, same reasoning as the two
    # repository methods this merges (list_open, list_all_for_employee).
    entries.sort(key=lambda e: e.created_at, reverse=True)
    total = len(entries)
    page = entries[offset : offset + limit]
    return GeofenceEventHistoryOut(items=page, total=total, limit=limit, offset=offset)


@router.get(
    "/{attendance_id}",
    response_model=AttendanceOut,
)
async def get_attendance(
    attendance_id: uuid.UUID,
    user: User = Depends(require_permission("attendance:read:all")),
    session: AsyncSession = Depends(get_db),
) -> AttendanceOut:
    attendance = await AttendanceService(session).get(attendance_id)
    if attendance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="attendance record not found")
    if user.role.name == "supervisor":
        own_employee = await _resolve_employee(user, session)
        # 404, not 403 — a supervisor probing another department's record
        # IDs must not be able to distinguish "not yours" from "doesn't exist".
        if (
            own_employee.department_id is None
            or attendance.employee.department_id != own_employee.department_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="attendance record not found"
            )
    return AttendanceOut.model_validate(attendance)


@router.post(
    "/{employee_id}/manual-entry",
    response_model=AttendanceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("attendance:correct"))],
)
async def create_manual_entry(
    employee_id: uuid.UUID, body: ManualEntryRequest, session: AsyncSession = Depends(get_db)
) -> AttendanceOut:
    try:
        attendance = await AttendanceService(session).create_manual_entry(
            employee_id, body.attendance_date, body.check_in_at, body.check_out_at, body.status, body.notes
        )
    except EmployeeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AlreadyCheckedInError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AttendanceOut.model_validate(attendance)


@router.patch(
    "/{attendance_id}",
    response_model=AttendanceOut,
    dependencies=[Depends(require_permission("attendance:correct"))],
)
async def correct_attendance(
    attendance_id: uuid.UUID, body: AttendanceCorrection, session: AsyncSession = Depends(get_db)
) -> AttendanceOut:
    service = AttendanceService(session)
    attendance = await service.get(attendance_id)
    if attendance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="attendance record not found")

    fields = body.model_dump(exclude_unset=True)
    await service.apply_correction(
        attendance,
        check_in_at=fields.get("check_in_at"),
        check_in_at_set="check_in_at" in fields,
        check_out_at=fields.get("check_out_at"),
        check_out_at_set="check_out_at" in fields,
        status=fields.get("status"),
        status_set="status" in fields,
        notes=fields.get("notes"),
        notes_set="notes" in fields,
    )
    return AttendanceOut.model_validate(attendance)
