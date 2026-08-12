import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.core.exceptions import (
    DepartmentNotFoundError,
    EmployeeNotFoundError,
    InvalidRoleError,
    SelfSupervisionError,
    UserAlreadyExistsError,
)
from app.models.employee import Employee
from app.models.user import User
from app.schemas.auth import UserOut
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeListOut,
    EmployeeOut,
    EmployeeStatusUpdate,
    EmployeeUpdate,
)
from app.services.employee_service import EmployeeService

router = APIRouter(prefix="/employees", tags=["employees"])


def _employee_out(employee: Employee) -> EmployeeOut:
    user = employee.user
    return EmployeeOut(
        id=employee.id,
        employee_code=employee.employee_code,
        user=UserOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role.name,
            is_active=user.is_active,
            is_verified=user.is_verified,
        ),
        department_id=employee.department_id,
        supervisor_id=employee.supervisor_id,
        job_title=employee.job_title,
        phone_number=employee.phone_number,
        hire_date=employee.hire_date,
        status=employee.status,
    )


@router.post(
    "",
    response_model=EmployeeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("users:write"))],
)
async def create_employee(
    body: EmployeeCreate, session: AsyncSession = Depends(get_db)
) -> EmployeeOut:
    try:
        employee = await EmployeeService(session).onboard(
            email=body.email,
            full_name=body.full_name,
            password=body.password,
            role_name=body.role_name,
            department_id=body.department_id,
            supervisor_id=body.supervisor_id,
            job_title=body.job_title,
            phone_number=body.phone_number,
            hire_date=body.hire_date,
        )
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (InvalidRoleError, DepartmentNotFoundError, EmployeeNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _employee_out(employee)


@router.get(
    "",
    response_model=EmployeeListOut,
    dependencies=[Depends(require_permission("users:read"))],
)
async def list_employees(
    department_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_permission("users:read")),
    session: AsyncSession = Depends(get_db),
) -> EmployeeListOut:
    # Same department-scoping rule as attendance.list_all_attendance: a
    # supervisor is confined to their own department, everyone above that
    # sees the whole company. A requested department_id outside a
    # supervisor's own is rejected rather than silently overridden.
    service = EmployeeService(session)
    if user.role.name == "supervisor":
        own_employee = await service.get_or_create_own_profile(user)
        if own_employee is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="no employee profile for this account"
            )
        if department_id is not None and department_id != own_employee.department_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="supervisors may only view their own department",
            )
        if own_employee.department_id is None:
            # A department_id of None means "no filter" to list_paginated —
            # for a supervisor with no department assigned, that would
            # return the whole company instead of nothing. Short-circuit.
            return EmployeeListOut(items=[], total=0, limit=limit, offset=offset)
        department_id = own_employee.department_id

    employees, total = await service.list_paginated(department_id, limit, offset)
    return EmployeeListOut(
        items=[_employee_out(e) for e in employees], total=total, limit=limit, offset=offset
    )


@router.get("/me", response_model=EmployeeOut)
async def get_my_employee_profile(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
) -> EmployeeOut:
    employee = await EmployeeService(session).get_or_create_own_profile(user)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no employee profile for this account"
        )
    return _employee_out(employee)


@router.get(
    "/{employee_id}",
    response_model=EmployeeOut,
)
async def get_employee(
    employee_id: uuid.UUID,
    user: User = Depends(require_permission("users:read")),
    session: AsyncSession = Depends(get_db),
) -> EmployeeOut:
    service = EmployeeService(session)
    employee = await service.get(employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    if user.role.name == "supervisor":
        own_employee = await service.get_or_create_own_profile(user)
        # 404, not 403 — same reasoning as attendance.get_attendance: a
        # supervisor probing another department's employee IDs must not be
        # able to distinguish "not yours" from "doesn't exist".
        if (
            own_employee is None
            or own_employee.department_id is None
            or employee.department_id != own_employee.department_id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    return _employee_out(employee)


@router.patch(
    "/{employee_id}",
    response_model=EmployeeOut,
    dependencies=[Depends(require_permission("users:write"))],
)
async def update_employee(
    employee_id: uuid.UUID, body: EmployeeUpdate, session: AsyncSession = Depends(get_db)
) -> EmployeeOut:
    service = EmployeeService(session)
    employee = await service.get(employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")

    fields = body.model_dump(exclude_unset=True)
    try:
        await service.update(
            employee,
            department_id=fields.get("department_id"),
            department_id_set="department_id" in fields,
            supervisor_id=fields.get("supervisor_id"),
            supervisor_id_set="supervisor_id" in fields,
            job_title=fields.get("job_title"),
            phone_number=fields.get("phone_number"),
        )
    except (DepartmentNotFoundError, EmployeeNotFoundError, SelfSupervisionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _employee_out(employee)


@router.patch(
    "/{employee_id}/status",
    response_model=EmployeeOut,
    dependencies=[Depends(require_permission("users:delete"))],
)
async def update_employee_status(
    employee_id: uuid.UUID, body: EmployeeStatusUpdate, session: AsyncSession = Depends(get_db)
) -> EmployeeOut:
    service = EmployeeService(session)
    employee = await service.get(employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="employee not found")
    await service.set_status(employee, body.status)
    return _employee_out(employee)
