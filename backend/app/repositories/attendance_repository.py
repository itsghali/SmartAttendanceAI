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
        is_jailbroken: bool = False,
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
            check_in_is_jailbroken=is_jailbroken,
        )
        self._session.add(attendance)
        await self._session.flush()
        return await self.get_by_id(attendance.id)

    async def bulk_create_synthetic(self, rows: list[dict]) -> list[Attendance]:
        """Bulk-insert pre-built synthetic Attendance rows in one flush
        (PLAN.md T12) — not a loop of create_check_in(), which is built for
        the single-row live check-in path (one flush per call, no
        synthetic_run_id/synthetic_anomaly_type parameters) and would be
        O(n) round trips for a batch generation run. is_synthetic=True is
        hardcoded here, never taken from the caller's dict, so this method
        can never be reused to accidentally write a real-looking row.
        Returns rows in the same order as the input, with ids populated, so
        the caller can attach BreakPeriod/GeofenceEvent rows to the right
        attendance_id."""
        records = [Attendance(is_synthetic=True, **row) for row in rows]
        self._session.add_all(records)
        await self._session.flush()
        return records

    async def list_for_baseline_including_synthetic(
        self, employee_ids: list[uuid.UUID], date_from: date, date_to: date
    ) -> list[Attendance]:
        """Module 2's ONE legitimate exception to the T0/T1 rule ("every read
        path filters is_synthetic=false by default") — a baseline built only
        from real history would be empty right now (synthetic data is this
        system's only bootstrap corpus per PLAN.md), so this deliberately
        returns BOTH real and synthetic rows. Do not reuse this method for
        anything HR/Admin-facing; it exists only for
        workforce_intelligence_service's baseline rebuild. Eager-loads
        breaks + geofence_events (not employee/check_in_geofence/
        check_out_geofence — the baseline builder never touches those) so
        the whole batch is one round trip, not N+1 (PLAN.md T7)."""
        if not employee_ids:
            return []
        stmt = (
            select(Attendance)
            .options(selectinload(Attendance.breaks), selectinload(Attendance.geofence_events))
            .where(
                Attendance.employee_id.in_(employee_ids),
                Attendance.attendance_date >= date_from,
                Attendance.attendance_date <= date_to,
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def has_any_for_employee(self, employee_id: uuid.UUID) -> bool:
        """Cheap existence check (real OR synthetic rows) — lets the
        workforce-intelligence daily job (app/core/scheduler.py) decide
        whether an employee still needs a one-time synthetic bootstrap
        corpus before a baseline can be built, without loading any rows."""
        stmt = select(Attendance.id).where(Attendance.employee_id == employee_id).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_by_id(self, attendance_id: uuid.UUID) -> Attendance | None:
        stmt = (
            select(Attendance)
            .options(*_EAGER)
            .where(Attendance.id == attendance_id, Attendance.is_synthetic.is_(False))
        )
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
                Attendance.is_synthetic.is_(False),
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
        out of this query itself.

        is_synthetic=False is load-bearing here, not decorative (PLAN.md T0):
        this query feeds the live, check-in-BLOCKING impossible-travel gate
        (attendance_service._check_impossible_travel_or_raise). Without this
        filter, a synthetic "far-away checkout" row (Workforce Intelligence's
        own generator, Sprint 3) would be compared against a real employee's
        next REAL check-in and could block it — a synthetic-data feature
        breaking a real employee's ability to check in.
        """
        stmt = (
            select(Attendance)
            .options(*_EAGER)
            .where(
                Attendance.employee_id == employee_id,
                Attendance.check_out_at.is_not(None),
                Attendance.is_synthetic.is_(False),
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
                Attendance.is_synthetic.is_(False),
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
                Attendance.is_synthetic.is_(False),
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
                Attendance.is_synthetic.is_(False),
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

    async def list_all_for_employee(
        self, employee_id: uuid.UUID, date_from: date | None, date_to: date | None
    ) -> list[Attendance]:
        """Every attendance session for one employee in range — unpaginated,
        same "bounded by realistic per-employee volume, not worth a second
        pagination axis" reasoning as list_open(). Feeds the History timeline's
        check-in/check-out entries (merged app-level with geofence_events in
        the route, then paginated together — see get_employee_geofence_history)."""
        stmt = (
            select(Attendance)
            .options(*_EAGER)
            .where(Attendance.employee_id == employee_id, Attendance.is_synthetic.is_(False))
        )
        if date_from is not None:
            stmt = stmt.where(Attendance.attendance_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Attendance.attendance_date <= date_to)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_open(self) -> list[Attendance]:
        """Every currently-open attendance session, company-wide — the roster
        behind the "Site status — today" exceptions screen. Deliberately not
        paginated: TODOS.md's own design calls this a "collapsed roster", not
        a paged list, and it's bounded by concurrently-working headcount, not
        historical volume, unlike list_paginated's callers. Also eager-loads
        employee.user (list_paginated's callers never need the employee's
        name, so that chain isn't in the shared _EAGER tuple) — the
        exceptions screen must show a name, not just employee_id (Codex
        outside-voice finding, eng review 2026-08-11), and skipping this
        eager-load would hit the same async lazy-load failure GeofenceEvent
        .geofence had.
        """
        stmt = (
            select(Attendance)
            .options(*_EAGER, selectinload(Attendance.employee).selectinload(Employee.user))
            .where(Attendance.check_out_at.is_(None), Attendance.is_synthetic.is_(False))
            .order_by(Attendance.check_in_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_paginated(
        self,
        employee_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Attendance], int]:
        stmt = select(Attendance).options(*_EAGER).where(Attendance.is_synthetic.is_(False))
        count_stmt = (
            select(func.count()).select_from(Attendance).where(Attendance.is_synthetic.is_(False))
        )

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
