import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attendance import Attendance, AttendanceStatus
from app.models.employee import Employee

# Attendance.employee is loaded for department-scoping checks (see
# attendance:read:all in routes/attendance.py) — user/role/permissions below
# it are never serialized or read anywhere, so that chain stops at Employee.
_EAGER = (
    selectinload(Attendance.employee),
    selectinload(Attendance.check_in_geofence),
    selectinload(Attendance.check_out_geofence),
    selectinload(Attendance.breaks),
    selectinload(Attendance.geofence_events),
)


class AttendanceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_check_in(
        self,
        employee_id: uuid.UUID,
        attendance_date: date,
        check_in_at: datetime,
        latitude: float | None,
        longitude: float | None,
        accuracy_meters: float | None,
        geofence_id: uuid.UUID | None,
        status: AttendanceStatus = AttendanceStatus.PRESENT,
        is_manual_entry: bool = False,
        notes: str = "",
    ) -> Attendance:
        attendance = Attendance(
            employee_id=employee_id,
            attendance_date=attendance_date,
            check_in_at=check_in_at,
            check_in_latitude=latitude,
            check_in_longitude=longitude,
            check_in_accuracy_meters=accuracy_meters,
            check_in_geofence_id=geofence_id,
            status=status,
            is_manual_entry=is_manual_entry,
            notes=notes,
        )
        self._session.add(attendance)
        await self._session.flush()
        return await self.get_by_id(attendance.id)

    async def get_by_id(self, attendance_id: uuid.UUID) -> Attendance | None:
        stmt = select(Attendance).options(*_EAGER).where(Attendance.id == attendance_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_for_employee_on_date(
        self, employee_id: uuid.UUID, attendance_date: date
    ) -> Attendance | None:
        """Any one session on that date.

        Kept only as an existence check (does this employee have a record that
        day at all) — for "the session happening right now" use
        get_open_for_employee, which is what check-out, breaks and location
        pings all mean.
        """
        stmt = (
            select(Attendance)
            .options(*_EAGER)
            .where(
                Attendance.employee_id == employee_id,
                Attendance.attendance_date == attendance_date,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_last_completed_for_employee(self, employee_id: uuid.UUID) -> Attendance | None:
        """Most recent CLOSED session (check_out_at is not None), regardless of
        date — the "last known position" for impossible-travel comparison
        against a new check-in. Manual/backfilled entries have no check_out
        coordinates (see create_manual_entry) and are naturally skipped by the
        caller checking check_out_latitude/longitude for None, not filtered
        out of this query itself."""
        stmt = (
            select(Attendance)
            .options(*_EAGER)
            .where(
                Attendance.employee_id == employee_id,
                Attendance.check_out_at.is_not(None),
            )
            .order_by(Attendance.check_out_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_open_for_employee(self, employee_id: uuid.UUID) -> Attendance | None:
        """The session the employee is currently inside, if any.

        Deliberately not filtered by date: a night shift started at 23:00 local
        is still the open session at 01:00 the next morning, and filtering by
        today's date is exactly what stopped those employees checking out.
        """
        stmt = (
            select(Attendance)
            .options(*_EAGER)
            .where(
                Attendance.employee_id == employee_id,
                Attendance.check_out_at.is_(None),
            )
            .order_by(Attendance.check_in_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_open_for_employee_locked(self, employee_id: uuid.UUID) -> Attendance | None:
        """Same as get_open_for_employee, but takes a row lock (SELECT ... FOR
        UPDATE) so two near-simultaneous pings for the same employee can't
        both read the pre-update outside_streak and both independently cross
        the exit debounce threshold — see record_ping in MonitoringService.
        Only used on the ping path; every other read stays lock-free.
        SQLite (used in tests) does not support FOR UPDATE and silently
        ignores the clause, which is fine — there's no real concurrency to
        guard against in a single-connection test run.
        """
        stmt = (
            select(Attendance)
            .options(*_EAGER)
            .where(
                Attendance.employee_id == employee_id,
                Attendance.check_out_at.is_(None),
            )
            .order_by(Attendance.check_in_at.desc())
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_for_employee_on_date(
        self, employee_id: uuid.UUID, attendance_date: date
    ) -> list[Attendance]:
        stmt = (
            select(Attendance)
            .options(*_EAGER)
            .where(
                Attendance.employee_id == employee_id,
                Attendance.attendance_date == attendance_date,
            )
            .order_by(Attendance.check_in_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def set_check_out(
        self,
        attendance: Attendance,
        check_out_at: datetime,
        latitude: float | None,
        longitude: float | None,
        accuracy_meters: float | None,
        geofence_id: uuid.UUID | None,
    ) -> None:
        attendance.check_out_at = check_out_at
        attendance.check_out_latitude = latitude
        attendance.check_out_longitude = longitude
        attendance.check_out_accuracy_meters = accuracy_meters
        attendance.check_out_geofence_id = geofence_id
        await self._session.flush()

    async def list_paginated(
        self,
        employee_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Attendance], int]:
        stmt = select(Attendance).options(*_EAGER)
        count_stmt = select(func.count()).select_from(Attendance)

        if department_id is not None:
            stmt = stmt.join(Employee, Attendance.employee_id == Employee.id).where(
                Employee.department_id == department_id
            )
            count_stmt = count_stmt.join(Employee, Attendance.employee_id == Employee.id).where(
                Employee.department_id == department_id
            )
        if employee_id is not None:
            stmt = stmt.where(Attendance.employee_id == employee_id)
            count_stmt = count_stmt.where(Attendance.employee_id == employee_id)
        if date_from is not None:
            stmt = stmt.where(Attendance.attendance_date >= date_from)
            count_stmt = count_stmt.where(Attendance.attendance_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Attendance.attendance_date <= date_to)
            count_stmt = count_stmt.where(Attendance.attendance_date <= date_to)

        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(Attendance.attendance_date.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def refresh_geofence_events(self, attendance: Attendance) -> None:
        """The identity map returns the same Python object on a re-fetch, and
        selectinload does not re-populate an already-loaded collection — so
        after inserting a GeofenceEvent for an attendance object already held
        in this session, the caller must explicitly refresh it to see the new
        row, a plain get_by_id() call is not enough."""
        await self._session.refresh(attendance, attribute_names=["geofence_events"])

    async def record_ping(
        self,
        attendance: Attendance,
        ping_seq: int,
        pinged_at: datetime,
        outside_streak: int,
    ) -> None:
        attendance.last_ping_seq = ping_seq
        attendance.last_ping_at = pinged_at
        attendance.outside_streak = outside_streak
        await self._session.flush()

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
        if check_in_at_set:
            attendance.check_in_at = check_in_at
        if check_out_at_set:
            attendance.check_out_at = check_out_at
        if status_set:
            attendance.status = status
        if notes_set:
            attendance.notes = notes
        await self._session.flush()
