import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DepartmentAlreadyExistsError
from app.models.department import Department
from app.repositories.department_repository import DepartmentRepository


class DepartmentService:
    def __init__(self, session: AsyncSession):
        self._repo = DepartmentRepository(session)

    async def create(
        self, name: str, description: str, manager_id: uuid.UUID | None
    ) -> Department:
        if await self._repo.get_by_name(name) is not None:
            raise DepartmentAlreadyExistsError(f"department '{name}' already exists")
        return await self._repo.create(name, description, manager_id)

    async def get(self, department_id: uuid.UUID) -> Department | None:
        return await self._repo.get_by_id(department_id)

    async def list_all(self) -> list[Department]:
        return await self._repo.list_all()

    async def update(
        self,
        department: Department,
        name: str | None,
        description: str | None,
        manager_id: uuid.UUID | None,
        manager_id_set: bool,
    ) -> None:
        if name is not None and name != department.name:
            if await self._repo.get_by_name(name) is not None:
                raise DepartmentAlreadyExistsError(f"department '{name}' already exists")
        await self._repo.update(department, name, description, manager_id, manager_id_set)

    async def delete(self, department: Department) -> None:
        await self._repo.delete(department)
