import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department


class DepartmentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, name: str, description: str, manager_id: uuid.UUID | None) -> Department:
        department = Department(name=name, description=description, manager_id=manager_id)
        self._session.add(department)
        await self._session.flush()
        return department

    async def get_by_id(self, department_id: uuid.UUID) -> Department | None:
        stmt = select(Department).where(Department.id == department_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_by_name(self, name: str) -> Department | None:
        stmt = select(Department).where(Department.name == name)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_all(self) -> list[Department]:
        stmt = select(Department).order_by(Department.name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        department: Department,
        name: str | None,
        description: str | None,
        manager_id: uuid.UUID | None,
        manager_id_set: bool,
    ) -> None:
        if name is not None:
            department.name = name
        if description is not None:
            department.description = description
        if manager_id_set:
            department.manager_id = manager_id
        await self._session.flush()

    async def delete(self, department: Department) -> None:
        await self._session.delete(department)
        await self._session.flush()
