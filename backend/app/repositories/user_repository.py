import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.mixins import utcnow
from app.models.role import Role
from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        stmt = (
            select(User)
            .options(selectinload(User.role).selectinload(Role.permissions))
            .where(User.email == email)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = (
            select(User)
            .options(selectinload(User.role).selectinload(Role.permissions))
            .where(User.id == user_id)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def create(
        self,
        email: str,
        hashed_password: str,
        full_name: str,
        role_id: uuid.UUID,
        phone_number: str | None = None,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            role_id=role_id,
            phone_number=phone_number,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def update_password(self, user: User, hashed_password: str) -> None:
        user.hashed_password = hashed_password
        user.updated_at = utcnow()
        await self._session.flush()

    async def mark_verified(self, user: User) -> None:
        user.is_verified = True
        await self._session.flush()
