import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mixins import utcnow
from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        device_id: uuid.UUID | None = None,
    ) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id, device_id=device_id, token_hash=token_hash, expires_at=expires_at
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_by_id(self, token_id: uuid.UUID) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.id == token_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = utcnow()
        await self._session.flush()

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
        result = await self._session.execute(stmt)
        for token in result.scalars().all():
            token.revoked_at = utcnow()
        await self._session.flush()

    async def revoke_all_for_device(self, device_id: uuid.UUID) -> None:
        stmt = select(RefreshToken).where(
            RefreshToken.device_id == device_id, RefreshToken.revoked_at.is_(None)
        )
        result = await self._session.execute(stmt)
        for token in result.scalars().all():
            token.revoked_at = utcnow()
        await self._session.flush()

    async def list_active_for_user(self, user_id: uuid.UUID) -> list[RefreshToken]:
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
        result = await self._session.execute(stmt)
        return [t for t in result.scalars().all() if t.is_active]
