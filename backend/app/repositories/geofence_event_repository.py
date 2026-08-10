import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def get_latest_for_attendance(self, attendance_id: uuid.UUID) -> GeofenceEvent | None:
        stmt = (
            select(GeofenceEvent)
            .where(GeofenceEvent.attendance_id == attendance_id)
            .order_by(GeofenceEvent.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()
