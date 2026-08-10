import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.repositories.refresh_token_repository import RefreshTokenRepository


class SessionService:
    def __init__(self, session: AsyncSession):
        self._refresh_tokens = RefreshTokenRepository(session)

    async def list_active_for_user(self, user_id: uuid.UUID) -> list[RefreshToken]:
        return await self._refresh_tokens.list_active_for_user(user_id)

    async def get_owned(
        self, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> RefreshToken | None:
        token = await self._refresh_tokens.get_by_id(session_id)
        if token is None or token.user_id != user_id:
            return None
        return token

    async def revoke(self, token: RefreshToken) -> None:
        await self._refresh_tokens.revoke(token)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self._refresh_tokens.revoke_all_for_user(user_id)
