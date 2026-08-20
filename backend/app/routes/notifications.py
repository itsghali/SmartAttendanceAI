"""Notification center API — Requirement 1's persistent, per-user
notification store. No dedicated permission code: a notification only ever
exists for a user who already held workforce_intelligence:read at the time
it was created (see NotificationService.notify_new_flags), and every route
here is scoped to the caller's own recipient_user_id, not a general list."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.notification import NotificationListOut, NotificationOut, UnreadCountOut
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListOut)
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> NotificationListOut:
    items, total = await NotificationService(session).list_for_user(
        user.id, unread_only, limit, offset
    )
    return NotificationListOut(
        items=[NotificationOut.model_validate(n) for n in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UnreadCountOut:
    count = await NotificationService(session).count_unread(user.id)
    return UnreadCountOut(unread_count=count)


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> NotificationOut:
    notification = await NotificationService(session).mark_read(notification_id, user.id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="notification not found")
    return NotificationOut.model_validate(notification)
