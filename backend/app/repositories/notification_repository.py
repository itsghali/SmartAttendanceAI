import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import EmailStatus, Notification


class NotificationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_if_new(self, row: dict) -> Notification | None:
        """Returns the created Notification, or None if a row for this
        (recipient_user_id, dedupe_key) already exists — the unique
        constraint is the actual guard (see Notification's docstring). Each
        attempt runs in its own SAVEPOINT (not a full session.rollback())
        because this is called from inside WorkforceIntelligenceService
        .run_detection's transaction, which by this point already has
        flushed-but-uncommitted EmployeeDeviationFlag rows sitting in the
        same session — a bare rollback() would wipe those out too, not just
        this one duplicate insert."""
        notification = Notification(**row)
        try:
            async with self._session.begin_nested():
                self._session.add(notification)
                await self._session.flush()
        except IntegrityError:
            return None
        return notification

    async def list_pending_digest_by_recipient(self) -> dict[uuid.UUID, list[Notification]]:
        stmt = select(Notification).where(Notification.email_status == EmailStatus.PENDING_DIGEST)
        result = await self._session.execute(stmt)
        by_recipient: dict[uuid.UUID, list[Notification]] = {}
        for n in result.scalars().all():
            by_recipient.setdefault(n.recipient_user_id, []).append(n)
        return by_recipient

    async def mark_digest_sent(self, notifications: list[Notification], sent_at: datetime) -> None:
        for n in notifications:
            n.email_status = EmailStatus.SENT
            n.email_sent_at = sent_at
        await self._session.flush()

    async def list_paginated(
        self,
        recipient_user_id: uuid.UUID,
        unread_only: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Notification], int]:
        stmt = select(Notification).where(Notification.recipient_user_id == recipient_user_id)
        count_stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.recipient_user_id == recipient_user_id)
        )
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
            count_stmt = count_stmt.where(Notification.is_read.is_(False))
        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(Notification.detected_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_unread(self, recipient_user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.recipient_user_id == recipient_user_id,
                Notification.is_read.is_(False),
            )
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        return await self._session.get(Notification, notification_id)

    async def mark_read(self, notification: Notification, read_at: datetime) -> Notification:
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = read_at
            await self._session.flush()
        return notification
