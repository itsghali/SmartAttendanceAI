import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.break_period import BreakPeriod, BreakSource


class BreakPeriodRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def start(
        self,
        attendance_id: uuid.UUID,
        break_start_at: datetime,
        latitude: float | None = None,
        longitude: float | None = None,
        accuracy_meters: float | None = None,
        geofence_id: uuid.UUID | None = None,
        source: BreakSource = BreakSource.MANUAL,
    ) -> BreakPeriod:
        break_period = BreakPeriod(
            attendance_id=attendance_id,
            source=source,
            break_start_at=break_start_at,
            start_latitude=latitude,
            start_longitude=longitude,
            start_accuracy_meters=accuracy_meters,
            start_geofence_id=geofence_id,
        )
        self._session.add(break_period)
        await self._session.flush()
        return break_period

    async def bulk_create_synthetic(self, rows: list[dict]) -> list[BreakPeriod]:
        """Mirrors AttendanceRepository.bulk_create_synthetic (PLAN.md T12) —
        one flush for the whole batch, is_synthetic=True hardcoded here."""
        records = [BreakPeriod(is_synthetic=True, **row) for row in rows]
        self._session.add_all(records)
        await self._session.flush()
        return records

    async def get_open_for_attendance(self, attendance_id: uuid.UUID) -> BreakPeriod | None:
        stmt = select(BreakPeriod).where(
            BreakPeriod.attendance_id == attendance_id,
            BreakPeriod.break_end_at.is_(None),
            BreakPeriod.is_synthetic.is_(False),
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def end(
        self,
        break_period: BreakPeriod,
        break_end_at: datetime,
        latitude: float | None = None,
        longitude: float | None = None,
        accuracy_meters: float | None = None,
        geofence_id: uuid.UUID | None = None,
    ) -> None:
        break_period.break_end_at = break_end_at
        break_period.end_latitude = latitude
        break_period.end_longitude = longitude
        break_period.end_accuracy_meters = accuracy_meters
        break_period.end_geofence_id = geofence_id
        await self._session.flush()
