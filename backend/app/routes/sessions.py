import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.models.user import User
from app.schemas.auth import SessionOut
from app.services.session_service import SessionService

router = APIRouter(tags=["sessions"])


@router.get("/sessions", response_model=list[SessionOut])
async def list_my_sessions(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
) -> list[SessionOut]:
    tokens = await SessionService(session).list_active_for_user(user.id)
    return [SessionOut.model_validate(t) for t in tokens]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    service = SessionService(session)
    token = await service.get_owned(user.id, session_id)
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    await service.revoke(token)


@router.delete("/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_my_sessions(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
) -> None:
    await SessionService(session).revoke_all_for_user(user.id)


@router.get(
    "/users/{user_id}/sessions",
    response_model=list[SessionOut],
    dependencies=[Depends(require_permission("sessions:manage:all"))],
)
async def list_user_sessions(
    user_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> list[SessionOut]:
    tokens = await SessionService(session).list_active_for_user(user_id)
    return [SessionOut.model_validate(t) for t in tokens]


@router.delete(
    "/users/{user_id}/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("sessions:manage:all"))],
)
async def revoke_user_sessions(user_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> None:
    await SessionService(session).revoke_all_for_user(user_id)
