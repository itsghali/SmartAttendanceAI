import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee, EmployeeStatus
from app.models.role import Role
from app.models.user import User

_EAGER = (
    selectinload(Employee.user).selectinload(User.role).selectinload(Role.permissions),
    selectinload(Employee.department),
)


class EmployeeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        user_id: uuid.UUID,
        employee_code: str,
        department_id: uuid.UUID | None,
        job_title: str,
        phone_number: str,
        hire_date: date,
        supervisor_id: uuid.UUID | None,
    ) -> Employee:
        employee = Employee(
            user_id=user_id,
            employee_code=employee_code,
            department_id=department_id,
            job_title=job_title,
            phone_number=phone_number,
            hire_date=hire_date,
            supervisor_id=supervisor_id,
        )
        self._session.add(employee)
        await self._session.flush()
        return employee

    async def get_by_id(self, employee_id: uuid.UUID) -> Employee | None:
        stmt = select(Employee).options(*_EAGER).where(Employee.id == employee_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_by_user_id(self, user_id: uuid.UUID) -> Employee | None:
        stmt = select(Employee).options(*_EAGER).where(Employee.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def get_by_code(self, employee_code: str) -> Employee | None:
        stmt = select(Employee).where(Employee.employee_code == employee_code)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(Employee)
        return (await self._session.execute(stmt)).scalar_one()

    async def generate_code(self) -> str:
        base = await self.count_all() + 1
        for offset in range(10):
            code = f"EMP-{base + offset:04d}"
            if await self.get_by_code(code) is None:
                return code
        raise RuntimeError("could not generate a unique employee code")

    async def list_paginated(
        self, department_id: uuid.UUID | None, limit: int, offset: int
    ) -> tuple[list[Employee], int]:
        stmt = select(Employee).options(*_EAGER)
        count_stmt = select(func.count()).select_from(Employee)
        if department_id is not None:
            stmt = stmt.where(Employee.department_id == department_id)
            count_stmt = count_stmt.where(Employee.department_id == department_id)

        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(Employee.employee_code).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def update(
        self,
        employee: Employee,
        department_id: uuid.UUID | None,
        department_id_set: bool,
        supervisor_id: uuid.UUID | None,
        supervisor_id_set: bool,
        job_title: str | None,
        phone_number: str | None,
    ) -> None:
        if department_id_set:
            employee.department_id = department_id
        if supervisor_id_set:
            employee.supervisor_id = supervisor_id
        if job_title is not None:
            employee.job_title = job_title
        if phone_number is not None:
            employee.phone_number = phone_number
        await self._session.flush()

    async def set_status(self, employee: Employee, status: EmployeeStatus) -> None:
        employee.status = status
        await self._session.flush()
