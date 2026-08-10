import base64
import binascii
import uuid
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.exceptions import (
    AlreadyCheckedInError,
    AlreadyCheckedOutError,
    BreakAlreadyActiveError,
    BreakStillActiveError,
    EmployeeNotFoundError,
    InvalidImageError,
    NoActiveBreakError,
    NoActiveGeofenceError,
    NotCheckedInError,
    OutsideGeofenceError,
    PoorLocationAccuracyError,
)
from app.core.geo import (
    Coordinates,
    haversine_distance_meters,
    is_within_polygon,
    polygon_centroid,
)
from app.models.attendance import Attendance, AttendanceStatus
from app.models.break_period import BreakPeriod
from app.models.employee import Employee
from app.models.geofence import Geofence, GeofenceBoundaryType
from app.models.geofence_event import GeofenceEventType
from app.models.mixins import utcnow
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.break_period_repository import BreakPeriodRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.geofence_event_repository import GeofenceEventRepository
from app.repositories.geofence_repository import GeofenceRepository
from app.services.face_service import FaceService


class AttendanceService:
    def __init__(self, session: AsyncSession):
        self._employees = EmployeeRepository(session)
        self._geofences = GeofenceRepository(session)
        self._attendance = AttendanceRepository(session)
        self._breaks = BreakPeriodRepository(session)
        self._geofence_events = GeofenceEventRepository(session)
        self._face = FaceService(session)
        self._settings = get_settings()

    def _match_geofence(
        self, candidates: list[Geofence], position: Coordinates
    ) -> Geofence | None:
        best: Geofence | None = None
        best_distance: float | None = None
        for geofence in candidates:
            if geofence.boundary_type == GeofenceBoundaryType.POLYGON:
                points = [Coordinates(p["latitude"], p["longitude"]) for p in geofence.polygon_points]
                if not is_within_polygon(position, points):
                    continue
                distance = haversine_distance_meters(position, polygon_centroid(points))
            else:
                center = Coordinates(geofence.center_latitude, geofence.center_longitude)
                distance = haversine_distance_meters(position, center)
                if distance > geofence.radius_meters:
                    continue
            if best_distance is None or distance < best_distance:
                best = geofence
                best_distance = distance
        return best

    def _check_accuracy(self, accuracy_meters: float | None) -> None:
        if (
            accuracy_meters is not None
            and accuracy_meters > self._settings.attendance_max_accuracy_meters
        ):
            raise PoorLocationAccuracyError(
                f"GPS accuracy {accuracy_meters}m exceeds the "
                f"{self._settings.attendance_max_accuracy_meters}m maximum"
            )

    async def _match_or_raise(
        self,
        employee: Employee,
        position: Coordinates,
        also_include_geofence_id: uuid.UUID | None = None,
    ) -> Geofence:
        # also_include_geofence_id: for check-out/break actions, the geofence an
        # employee already checked into stays a valid match for THIS attendance
        # even if HR deactivates it mid-shift — deactivation stops new check-ins,
        # it must not strand someone standing exactly where they're supposed to
        # be with no self-service way to end their shift.
        candidates = await self._geofences.list_active_for_employee(
            employee.id, employee.department_id
        )
        if also_include_geofence_id is not None and not any(
            g.id == also_include_geofence_id for g in candidates
        ):
            still_valid_geofence = await self._geofences.get_by_id(also_include_geofence_id)
            if still_valid_geofence is not None:
                candidates.append(still_valid_geofence)
        if not candidates:
            raise NoActiveGeofenceError("no active geofence configured for this employee")
        matched = self._match_geofence(candidates, position)
        if matched is None:
            raise OutsideGeofenceError("location is outside every eligible geofence")
        return matched

    async def _verify_face_or_raise(self, employee: Employee, selfie_base64: str | None) -> None:
        if not self._settings.face_verification_enabled:
            return
        if selfie_base64 is None:
            raise InvalidImageError("a selfie is required to check in")
        try:
            image_bytes = base64.b64decode(selfie_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidImageError("selfie_base64 is not valid base64") from exc
        # Same size cap /face/enroll and /face/verify enforce on their multipart
        # uploads (face.py's _read_and_validate) — without it, this JSON path
        # could decode an arbitrarily large image and feed it straight into the
        # CPU-bound ONNX pipeline on every check-in/check-out/break call.
        max_bytes = self._settings.face_max_upload_size_mb * 1024 * 1024
        if len(image_bytes) > max_bytes:
            raise InvalidImageError(
                f"image exceeds max size of {self._settings.face_max_upload_size_mb}MB"
            )
        # Raises FaceProfileNotFoundError / LivenessCheckFailedError /
        # FaceMismatchError / NoFaceDetectedError / MultipleFacesDetectedError /
        # InvalidImageError / FaceModelUnavailableError — all propagate to the
        # route unchanged, same as every other check-in rejection reason.
        await self._face.verify(employee.id, image_bytes)

    async def check_in(
        self,
        employee: Employee,
        latitude: float,
        longitude: float,
        accuracy_meters: float | None,
        selfie_base64: str | None = None,
    ) -> Attendance:
        today = utcnow().date()
        # An employee works several chantiers a day, so the limit is not one
        # check-in per day — it is one OPEN session at a time.
        if await self._attendance.get_open_for_employee(employee.id) is not None:
            raise AlreadyCheckedInError("check out of your current site before checking in again")

        self._check_accuracy(accuracy_meters)
        matched = await self._match_or_raise(employee, Coordinates(latitude, longitude))
        # Geofence match (cheap) already passed above before this runs the ML
        # pipeline — no wasted face compute on a check-in that was going to be
        # rejected anyway.
        await self._verify_face_or_raise(employee, selfie_base64)

        # No same-site restriction on purpose. Returning to the site just left —
        # after lunch, a supply run, moving a machine — is ordinary, and the
        # geofence gate already proves the employee is physically there. The one
        # rule is that the previous session must be closed first.

        # Two simultaneous check-in requests both pass the open-session check
        # above before either commits — the partial unique index
        # (uq_attendance_one_open_session) is the real backstop. Without this
        # rescue the loser gets an unhandled 500 instead of the same 409 a slower
        # client would see (see PLAN.md Eng review — CRITICAL REGRESSION, T1).
        try:
            attendance = await self._attendance.create_check_in(
                employee_id=employee.id,
                attendance_date=today,
                check_in_at=utcnow(),
                latitude=latitude,
                longitude=longitude,
                accuracy_meters=accuracy_meters,
                geofence_id=matched.id,
            )
        except IntegrityError as exc:
            raise AlreadyCheckedInError(
                "check out of your current site before checking in again"
            ) from exc

        await self._geofence_events.create(
            employee.id, attendance.id, matched.id, GeofenceEventType.ENTER, latitude, longitude
        )
        # attendance's geofence_events collection was eager-loaded (empty)
        # before the ENTER event existed — a plain re-fetch returns the same
        # identity-mapped object without reloading it, so refresh explicitly.
        await self._attendance.refresh_geofence_events(attendance)
        return attendance

    async def check_out(
        self,
        employee: Employee,
        latitude: float,
        longitude: float,
        accuracy_meters: float | None,
        selfie_base64: str | None = None,
    ) -> Attendance:
        attendance = await self._attendance.get_open_for_employee(employee.id)
        if attendance is None:
            raise NotCheckedInError("you are not checked in at any site")
        if await self._breaks.get_open_for_attendance(attendance.id) is not None:
            raise BreakStillActiveError("end your break before checking out")

        self._check_accuracy(accuracy_meters)
        matched = await self._match_or_raise(
            employee, Coordinates(latitude, longitude), attendance.check_in_geofence_id
        )
        await self._verify_face_or_raise(employee, selfie_base64)

        await self._attendance.set_check_out(
            attendance, utcnow(), latitude, longitude, accuracy_meters, matched.id
        )
        return await self._attendance.get_by_id(attendance.id)

    async def _get_open_attendance_or_raise(self, employee_id: uuid.UUID) -> Attendance:
        attendance = await self._attendance.get_open_for_employee(employee_id)
        if attendance is None:
            raise NotCheckedInError("you are not checked in at any site")
        return attendance

    async def start_break(
        self,
        employee: Employee,
        latitude: float,
        longitude: float,
        accuracy_meters: float | None,
        selfie_base64: str | None = None,
    ) -> BreakPeriod:
        attendance = await self._get_open_attendance_or_raise(employee.id)
        if await self._breaks.get_open_for_attendance(attendance.id) is not None:
            raise BreakAlreadyActiveError("a break is already active")

        # Same gate as check_in/check_out — conflict checks first, then location,
        # so an employee who is already on break is told that rather than being
        # sent to fix a location problem that was never the reason for refusal.
        self._check_accuracy(accuracy_meters)
        matched = await self._match_or_raise(
            employee, Coordinates(latitude, longitude), attendance.check_in_geofence_id
        )
        await self._verify_face_or_raise(employee, selfie_base64)

        # Two simultaneous start_break requests both pass the open-break check
        # above before either commits — uq_break_period_one_open_per_attendance
        # is the real backstop, mirroring the check_in() rescue above.
        try:
            return await self._breaks.start(
                attendance.id, utcnow(), latitude, longitude, accuracy_meters, matched.id
            )
        except IntegrityError as exc:
            raise BreakAlreadyActiveError("a break is already active") from exc

    async def end_break(
        self,
        employee: Employee,
        latitude: float,
        longitude: float,
        accuracy_meters: float | None,
        selfie_base64: str | None = None,
    ) -> BreakPeriod:
        attendance = await self._get_open_attendance_or_raise(employee.id)
        open_break = await self._breaks.get_open_for_attendance(attendance.id)
        if open_break is None:
            raise NoActiveBreakError("no active break to end")

        self._check_accuracy(accuracy_meters)
        matched = await self._match_or_raise(
            employee, Coordinates(latitude, longitude), attendance.check_in_geofence_id
        )
        await self._verify_face_or_raise(employee, selfie_base64)

        await self._breaks.end(
            open_break, utcnow(), latitude, longitude, accuracy_meters, matched.id
        )
        return open_break

    async def get_today(
        self, employee_id: uuid.UUID
    ) -> tuple[Attendance | None, list[Attendance]]:
        """(the session open right now, every session that started today).

        The open session is looked up independently of the date on purpose — a
        night shift started yesterday evening is still the current session, and
        it would otherwise vanish from the app at midnight while still running.
        """
        current = await self._attendance.get_open_for_employee(employee_id)
        sessions = await self._attendance.list_for_employee_on_date(employee_id, utcnow().date())
        return current, sessions

    async def get(self, attendance_id: uuid.UUID) -> Attendance | None:
        return await self._attendance.get_by_id(attendance_id)

    async def list_for_employee(
        self, employee_id: uuid.UUID, date_from: date | None, date_to: date | None, limit: int, offset: int
    ) -> tuple[list[Attendance], int]:
        return await self._attendance.list_paginated(
            employee_id, None, date_from, date_to, limit, offset
        )

    async def list_all(
        self,
        employee_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Attendance], int]:
        return await self._attendance.list_paginated(
            employee_id, department_id, date_from, date_to, limit, offset
        )

    async def create_manual_entry(
        self,
        employee_id: uuid.UUID,
        attendance_date: date,
        check_in_at: datetime,
        check_out_at: datetime | None,
        status: AttendanceStatus,
        notes: str,
    ) -> Attendance:
        if await self._employees.get_by_id(employee_id) is None:
            raise EmployeeNotFoundError(f"employee {employee_id} not found")
        if await self._attendance.get_for_employee_on_date(employee_id, attendance_date) is not None:
            raise AlreadyCheckedInError(f"an attendance record already exists for {attendance_date}")

        attendance = await self._attendance.create_check_in(
            employee_id=employee_id,
            attendance_date=attendance_date,
            check_in_at=check_in_at,
            latitude=None,
            longitude=None,
            accuracy_meters=None,
            geofence_id=None,
            status=status,
            is_manual_entry=True,
            notes=notes,
        )
        if check_out_at is not None:
            await self._attendance.set_check_out(attendance, check_out_at, None, None, None, None)
            attendance = await self._attendance.get_by_id(attendance.id)
        return attendance

    async def apply_correction(
        self,
        attendance: Attendance,
        check_in_at: datetime | None,
        check_in_at_set: bool,
        check_out_at: datetime | None,
        check_out_at_set: bool,
        status: AttendanceStatus | None,
        status_set: bool,
        notes: str | None,
        notes_set: bool,
    ) -> None:
        await self._attendance.apply_correction(
            attendance,
            check_in_at,
            check_in_at_set,
            check_out_at,
            check_out_at_set,
            status,
            status_set,
            notes,
            notes_set,
        )
