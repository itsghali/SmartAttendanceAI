import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_permission
from app.core.exceptions import (
    DepartmentNotFoundError,
    EmployeeNotFoundError,
    GeofenceNotFoundError,
    PolygonInvalidError,
)
from app.schemas.geofence import (
    EmployeeGeofenceListOut,
    EmployeeGeofenceOut,
    GeofenceCreate,
    GeofenceListOut,
    GeofenceOut,
    GeofenceUpdate,
)
from app.services.geofence_service import GeofenceService

router = APIRouter(prefix="/geofences", tags=["geofences"])


@router.post(
    "",
    response_model=GeofenceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("geofences:write"))],
)
async def create_geofence(
    body: GeofenceCreate, session: AsyncSession = Depends(get_db)
) -> GeofenceOut:
    try:
        geofence = await GeofenceService(session).create(
            body.name,
            body.department_id,
            body.boundary_type,
            body.center_latitude,
            body.center_longitude,
            body.radius_meters,
            [p.model_dump() for p in body.polygon_points] if body.polygon_points else None,
        )
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PolygonInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GeofenceOut.model_validate(geofence)


@router.get(
    "",
    response_model=GeofenceListOut,
    dependencies=[Depends(require_permission("geofences:read"))],
)
async def list_geofences(
    department_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> GeofenceListOut:
    geofences, total = await GeofenceService(session).list_paginated(
        department_id, is_active, limit, offset
    )
    return GeofenceListOut(
        items=[GeofenceOut.model_validate(g) for g in geofences],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{geofence_id}",
    response_model=GeofenceOut,
    dependencies=[Depends(require_permission("geofences:read"))],
)
async def get_geofence(
    geofence_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> GeofenceOut:
    geofence = await GeofenceService(session).get(geofence_id)
    if geofence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="geofence not found")
    return GeofenceOut.model_validate(geofence)


@router.patch(
    "/{geofence_id}",
    response_model=GeofenceOut,
    dependencies=[Depends(require_permission("geofences:write"))],
)
async def update_geofence(
    geofence_id: uuid.UUID, body: GeofenceUpdate, session: AsyncSession = Depends(get_db)
) -> GeofenceOut:
    service = GeofenceService(session)
    geofence = await service.get(geofence_id)
    if geofence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="geofence not found")

    fields = body.model_dump(exclude_unset=True)
    polygon_points = fields.get("polygon_points")
    try:
        await service.update(
            geofence,
            name=fields.get("name"),
            department_id=fields.get("department_id"),
            department_id_set="department_id" in fields,
            boundary_type=fields.get("boundary_type"),
            center_latitude=fields.get("center_latitude"),
            center_latitude_set="center_latitude" in fields,
            center_longitude=fields.get("center_longitude"),
            center_longitude_set="center_longitude" in fields,
            radius_meters=fields.get("radius_meters"),
            radius_meters_set="radius_meters" in fields,
            polygon_points=polygon_points,
            polygon_points_set="polygon_points" in fields,
            is_active=fields.get("is_active"),
            is_active_set="is_active" in fields,
        )
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PolygonInvalidError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GeofenceOut.model_validate(geofence)


@router.post(
    "/{geofence_id}/employees/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("geofences:write"))],
)
async def assign_employee(
    geofence_id: uuid.UUID, employee_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> None:
    try:
        await GeofenceService(session).assign_employee(geofence_id, employee_id)
    except GeofenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EmployeeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/{geofence_id}/employees/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("geofences:write"))],
)
async def unassign_employee(
    geofence_id: uuid.UUID, employee_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> None:
    try:
        await GeofenceService(session).unassign_employee(geofence_id, employee_id)
    except GeofenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{geofence_id}/employees",
    response_model=EmployeeGeofenceListOut,
    dependencies=[Depends(require_permission("geofences:read"))],
)
async def list_assigned_employees(
    geofence_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> EmployeeGeofenceListOut:
    try:
        employees = await GeofenceService(session).list_assigned_employees(geofence_id)
    except GeofenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return EmployeeGeofenceListOut(
        items=[
            EmployeeGeofenceOut(
                id=e.id, employee_code=e.employee_code, full_name=e.user.full_name, job_title=e.job_title
            )
            for e in employees
        ]
    )
