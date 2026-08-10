import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.break_period import BreakPeriod


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
    ) -> BreakPeriod:
        break_period = BreakPeriod(
            attendance_id=attendance_id,
            break_start_at=break_start_at,
            start_latitude=latitude,
            start_longitude=longitude,
            start_accuracy_meters=accuracy_meters,
            start_geofence_id=geofence_id,
        )
        self._session.add(break_period)
        await self._session.flush()
        return break_period

    async def get_open_for_attendance(self, attendance_id: uuid.UUID) -> BreakPeriod | None:
        stmt = select(BreakPeriod).where(
            BreakPeriod.attendance_id == attendance_id, BreakPeriod.break_end_at.is_(None)
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
