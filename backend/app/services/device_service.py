import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.repositories.device_repository import DeviceRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository


class DeviceService:
    def __init__(self, session: AsyncSession):
        self._devices = DeviceRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def list_for_user(self, user_id: uuid.UUID) -> list[Device]:
        return await self._devices.list_for_user(user_id)

    async def get_owned(self, user_id: uuid.UUID, device_id: uuid.UUID) -> Device | None:
        device = await self._devices.get_by_id(device_id)
        if device is None or device.user_id != user_id:
            return None
        return device

    async def revoke(self, device: Device) -> None:
        await self._refresh_tokens.revoke_all_for_device(device.id)
        await self._devices.delete(device)
