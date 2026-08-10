import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.models.user import User
from app.schemas.auth import DeviceOut
from app.services.device_service import DeviceService

router = APIRouter(tags=["devices"])


@router.get("/devices", response_model=list[DeviceOut])
async def list_my_devices(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
) -> list[DeviceOut]:
    devices = await DeviceService(session).list_for_user(user.id)
    return [DeviceOut.model_validate(d) for d in devices]


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_device(
    device_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    service = DeviceService(session)
    device = await service.get_owned(user.id, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device not found")
    await service.revoke(device)


@router.get(
    "/users/{user_id}/devices",
    response_model=list[DeviceOut],
    dependencies=[Depends(require_permission("devices:manage:all"))],
)
async def list_user_devices(
    user_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> list[DeviceOut]:
    devices = await DeviceService(session).list_for_user(user_id)
    return [DeviceOut.model_validate(d) for d in devices]


@router.delete(
    "/users/{user_id}/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("devices:manage:all"))],
)
async def revoke_user_device(
    user_id: uuid.UUID, device_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> None:
    service = DeviceService(session)
    device = await service.get_owned(user_id, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device not found")
    await service.revoke(device)
