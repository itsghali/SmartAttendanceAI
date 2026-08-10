import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_permission
from app.core.exceptions import DepartmentAlreadyExistsError
from app.schemas.department import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services.department_service import DepartmentService

router = APIRouter(prefix="/departments", tags=["departments"])


@router.post(
    "",
    response_model=DepartmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("users:write"))],
)
async def create_department(
    body: DepartmentCreate, session: AsyncSession = Depends(get_db)
) -> DepartmentOut:
    try:
        department = await DepartmentService(session).create(
            body.name, body.description, body.manager_id
        )
    except DepartmentAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return DepartmentOut.model_validate(department)


@router.get(
    "",
    response_model=list[DepartmentOut],
    dependencies=[Depends(require_permission("users:read"))],
)
async def list_departments(session: AsyncSession = Depends(get_db)) -> list[DepartmentOut]:
    departments = await DepartmentService(session).list_all()
    return [DepartmentOut.model_validate(d) for d in departments]


@router.get(
    "/{department_id}",
    response_model=DepartmentOut,
    dependencies=[Depends(require_permission("users:read"))],
)
async def get_department(
    department_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> DepartmentOut:
    department = await DepartmentService(session).get(department_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="department not found")
    return DepartmentOut.model_validate(department)


@router.patch(
    "/{department_id}",
    response_model=DepartmentOut,
    dependencies=[Depends(require_permission("users:write"))],
)
async def update_department(
    department_id: uuid.UUID, body: DepartmentUpdate, session: AsyncSession = Depends(get_db)
) -> DepartmentOut:
    service = DepartmentService(session)
    department = await service.get(department_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="department not found")

    fields = body.model_dump(exclude_unset=True)
    try:
        await service.update(
            department,
            name=fields.get("name"),
            description=fields.get("description"),
            manager_id=fields.get("manager_id"),
            manager_id_set="manager_id" in fields,
        )
    except DepartmentAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return DepartmentOut.model_validate(department)


@router.delete(
    "/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("users:delete"))],
)
async def delete_department(
    department_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> None:
    service = DepartmentService(session)
    department = await service.get(department_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="department not found")
    await service.delete(department)
