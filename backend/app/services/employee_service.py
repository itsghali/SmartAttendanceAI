import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DepartmentNotFoundError,
    EmployeeNotFoundError,
    InvalidRoleError,
    SelfSupervisionError,
    UserAlreadyExistsError,
)
from app.core.security import hash_password
from app.models.employee import Employee, EmployeeStatus
from app.models.otp import OTPPurpose
from app.repositories.department_repository import DepartmentRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService
from app.services.otp_service import OTPService


class EmployeeService:
    def __init__(self, session: AsyncSession, email_service: EmailService | None = None):
        self._users = UserRepository(session)
        self._roles = RoleRepository(session)
        self._departments = DepartmentRepository(session)
        self._employees = EmployeeRepository(session)
        self._otp = OTPService(session, email_service)

    async def _generate_employee_code(self) -> str:
        base = await self._employees.count_all() + 1
        for offset in range(10):
            code = f"EMP-{base + offset:04d}"
            if await self._employees.get_by_code(code) is None:
                return code
        raise RuntimeError("could not generate a unique employee code")

    async def onboard(
        self,
        email: str,
        full_name: str,
        password: str,
        role_name: str,
        department_id: uuid.UUID | None,
        supervisor_id: uuid.UUID | None,
        job_title: str,
        phone_number: str,
        hire_date: date,
    ) -> Employee:
        if await self._users.get_by_email(email) is not None:
            raise UserAlreadyExistsError(f"user with email {email} already exists")

        role = await self._roles.get_by_name(role_name)
        if role is None:
            raise InvalidRoleError(f"unknown role: {role_name}")

        if department_id is not None and await self._departments.get_by_id(department_id) is None:
            raise DepartmentNotFoundError(f"department {department_id} not found")

        if supervisor_id is not None and await self._employees.get_by_id(supervisor_id) is None:
            raise EmployeeNotFoundError(f"supervisor {supervisor_id} not found")

        user = await self._users.create(
            email=email, hashed_password=hash_password(password), full_name=full_name, role_id=role.id
        )
        user.role = role
        await self._users.mark_verified(user)

        code = await self._generate_employee_code()
        employee = await self._employees.create(
            user_id=user.id,
            employee_code=code,
            department_id=department_id,
            job_title=job_title,
            phone_number=phone_number,
            hire_date=hire_date,
            supervisor_id=supervisor_id,
        )
        employee.user = user

        # HR sets the initial password but it's never emailed; the employee
        # sets their own via the same OTP flow as a normal password reset.
        await self._otp.issue(user, OTPPurpose.PASSWORD_RESET)
        return employee

    async def get(self, employee_id: uuid.UUID) -> Employee | None:
        return await self._employees.get_by_id(employee_id)

    async def get_by_user_id(self, user_id: uuid.UUID) -> Employee | None:
        return await self._employees.get_by_user_id(user_id)

    async def list_paginated(
        self, department_id: uuid.UUID | None, limit: int, offset: int
    ) -> tuple[list[Employee], int]:
        return await self._employees.list_paginated(department_id, limit, offset)

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
        if department_id_set and department_id is not None:
            if await self._departments.get_by_id(department_id) is None:
                raise DepartmentNotFoundError(f"department {department_id} not found")

        if supervisor_id_set and supervisor_id is not None:
            if supervisor_id == employee.id:
                raise SelfSupervisionError("an employee cannot supervise themself")
            if await self._employees.get_by_id(supervisor_id) is None:
                raise EmployeeNotFoundError(f"supervisor {supervisor_id} not found")

        await self._employees.update(
            employee,
            department_id,
            department_id_set,
            supervisor_id,
            supervisor_id_set,
            job_title,
            phone_number,
        )

    async def set_status(self, employee: Employee, new_status: EmployeeStatus) -> None:
        await self._employees.set_status(employee, new_status)
        if new_status == EmployeeStatus.TERMINATED:
            user = await self._users.get_by_id(employee.user_id)
            if user is not None:
                user.is_active = False
