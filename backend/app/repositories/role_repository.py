from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.role import Role


class RoleRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_name(self, name: str) -> Role | None:
        stmt = select(Role).options(selectinload(Role.permissions)).where(Role.name == name)
        result = await self._session.execute(stmt)
        return result.scalars().first()
