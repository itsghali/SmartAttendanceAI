import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.geofence_event import GeofenceEvent, GeofenceEventType


class GeofenceEventRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        employee_id: uuid.UUID,
        attendance_id: uuid.UUID,
        geofence_id: uuid.UUID | None,
        event_type: GeofenceEventType,
        latitude: float,
        longitude: float,
    ) -> GeofenceEvent:
        event = GeofenceEvent(
            employee_id=employee_id,
            attendance_id=attendance_id,
            geofence_id=geofence_id,
            event_type=event_type,
            latitude=latitude,
            longitude=longitude,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def bulk_create_synthetic(self, rows: list[dict]) -> list[GeofenceEvent]:
        """Mirrors AttendanceRepository.bulk_create_synthetic (PLAN.md T12) —
        one flush for the whole batch, is_synthetic=True hardcoded here.
        Unlike Attendance/BreakPeriod, GeofenceEvent has no business
        timestamp column of its own — ordering is entirely on created_at, so
        the caller MUST pass an explicit created_at per row (the generator's
        computed ENTER/EXIT/RETURN offset) rather than let TimestampMixin's
        insert-time default apply, or a whole batch would collapse onto one
        real timestamp and lose event ordering."""
        records = [GeofenceEvent(is_synthetic=True, **row) for row in rows]
        self._session.add_all(records)
        await self._session.flush()
        return records

    async def get_latest_for_attendance(self, attendance_id: uuid.UUID) -> GeofenceEvent | None:
        stmt = (
            select(GeofenceEvent)
            .where(
                GeofenceEvent.attendance_id == attendance_id,
                GeofenceEvent.is_synthetic.is_(False),
            )
            .order_by(GeofenceEvent.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_all_for_employee(
        self,
        employee_id: uuid.UUID,
        date_from: date | None,
        date_to: date | None,
        event_type: GeofenceEventType | None,
    ) -> list[GeofenceEvent]:
        """Event-grain history for one employee — NOT attendance-session-grain.

        Deliberately its own query rather than a reuse of
        AttendanceRepository.list_paginated(): that method paginates attendance
        sessions (a session can hold 0-N events), so "50 rows" there means 50
        sessions, not 50 events, and its date filter is on attendance_date, not
        the event's own timestamp. Eager-loads .geofence explicitly — it is
        not covered by Attendance's eager-load of geofence_events, and
        omitting it hits an async lazy-load failure the first time a geofence
        name is rendered, not just an N+1.

        Unpaginated (was DB-paginated before the check-in/check-out merge):
        the route now merges this with AttendanceRepository.list_all_for_employee
        into one chronological timeline and paginates the merged result in
        Python, since a single SQL LIMIT/OFFSET can't paginate correctly
        across two different tables. Same "bounded by realistic per-employee
        volume" reasoning as list_open() and list_all_for_employee.
        """
        stmt = select(GeofenceEvent).options(selectinload(GeofenceEvent.geofence)).where(
            GeofenceEvent.employee_id == employee_id, GeofenceEvent.is_synthetic.is_(False)
        )
        if date_from is not None:
            start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
            stmt = stmt.where(GeofenceEvent.created_at >= start)
        if date_to is not None:
            end = datetime.combine(date_to, time.min, tzinfo=timezone.utc) + timedelta(days=1)
            stmt = stmt.where(GeofenceEvent.created_at < end)
        if event_type is not None:
            stmt = stmt.where(GeofenceEvent.event_type == event_type)

        stmt = stmt.order_by(GeofenceEvent.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
