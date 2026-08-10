import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.mixins import utcnow


class DeviceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_identifier(
        self, user_id: uuid.UUID, device_identifier: str
    ) -> Device | None:
        stmt = select(Device).where(
            Device.user_id == user_id, Device.device_identifier == device_identifier
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_by_id(self, device_id: uuid.UUID) -> Device | None:
        stmt = select(Device).where(Device.id == device_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def create(
        self, user_id: uuid.UUID, device_identifier: str, device_name: str, platform: str
    ) -> Device:
        device = Device(
            user_id=user_id,
            device_identifier=device_identifier,
            device_name=device_name,
            platform=platform,
        )
        self._session.add(device)
        await self._session.flush()
        return device

    async def touch(self, device: Device) -> None:
        device.last_seen_at = utcnow()
        await self._session.flush()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Device]:
        stmt = select(Device).where(Device.user_id == user_id).order_by(Device.last_seen_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, device: Device) -> None:
        await self._session.delete(device)
        await self._session.flush()
