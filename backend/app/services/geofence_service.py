import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DepartmentNotFoundError,
    EmployeeNotFoundError,
    GeofenceNotFoundError,
    PolygonInvalidError,
)
from app.models.employee import Employee
from app.models.geofence import Geofence, GeofenceBoundaryType
from app.repositories.department_repository import DepartmentRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.geofence_repository import GeofenceRepository

_MIN_POLYGON_POINTS = 3


def _validate_boundary(
    boundary_type: GeofenceBoundaryType,
    center_latitude: float | None,
    center_longitude: float | None,
    radius_meters: float | None,
    polygon_points: list[dict] | None,
) -> None:
    if boundary_type == GeofenceBoundaryType.CIRCLE:
        if center_latitude is None or center_longitude is None or radius_meters is None:
            raise PolygonInvalidError(
                "circle geofences require center_latitude, center_longitude, and radius_meters"
            )
    else:
        if polygon_points is None or len(polygon_points) < _MIN_POLYGON_POINTS:
            raise PolygonInvalidError(
                f"polygon geofences require at least {_MIN_POLYGON_POINTS} points"
            )


class GeofenceService:
    def __init__(self, session: AsyncSession):
        self._repo = GeofenceRepository(session)
        self._departments = DepartmentRepository(session)
        self._employees = EmployeeRepository(session)

    async def create(
        self,
        name: str,
        department_id: uuid.UUID | None,
        boundary_type: GeofenceBoundaryType,
        center_latitude: float | None,
        center_longitude: float | None,
        radius_meters: float | None,
        polygon_points: list[dict] | None,
    ) -> Geofence:
        if department_id is not None and await self._departments.get_by_id(department_id) is None:
            raise DepartmentNotFoundError(f"department {department_id} not found")
        _validate_boundary(boundary_type, center_latitude, center_longitude, radius_meters, polygon_points)
        return await self._repo.create(
            name,
            department_id,
            boundary_type,
            center_latitude,
            center_longitude,
            radius_meters,
            polygon_points,
        )

    async def get(self, geofence_id: uuid.UUID) -> Geofence | None:
        return await self._repo.get_by_id(geofence_id)

    async def list_paginated(
        self, department_id: uuid.UUID | None, is_active: bool | None, limit: int, offset: int
    ) -> tuple[list[Geofence], int]:
        return await self._repo.list_paginated(department_id, is_active, limit, offset)

    async def update(
        self,
        geofence: Geofence,
        name: str | None,
        department_id: uuid.UUID | None,
        department_id_set: bool,
        boundary_type: GeofenceBoundaryType | None,
        center_latitude: float | None,
        center_latitude_set: bool,
        center_longitude: float | None,
        center_longitude_set: bool,
        radius_meters: float | None,
        radius_meters_set: bool,
        polygon_points: list[dict] | None,
        polygon_points_set: bool,
        is_active: bool | None,
        is_active_set: bool,
    ) -> None:
        if department_id_set and department_id is not None:
            if await self._departments.get_by_id(department_id) is None:
                raise DepartmentNotFoundError(f"department {department_id} not found")

        effective_boundary_type = boundary_type or geofence.boundary_type
        effective_center_latitude = (
            center_latitude if center_latitude_set else geofence.center_latitude
        )
        effective_center_longitude = (
            center_longitude if center_longitude_set else geofence.center_longitude
        )
        effective_radius_meters = radius_meters if radius_meters_set else geofence.radius_meters
        effective_polygon_points = (
            polygon_points if polygon_points_set else geofence.polygon_points
        )
        _validate_boundary(
            effective_boundary_type,
            effective_center_latitude,
            effective_center_longitude,
            effective_radius_meters,
            effective_polygon_points,
        )

        await self._repo.update(
            geofence,
            name,
            department_id,
            department_id_set,
            boundary_type,
            center_latitude,
            center_latitude_set,
            center_longitude,
            center_longitude_set,
            radius_meters,
            radius_meters_set,
            polygon_points,
            polygon_points_set,
            is_active,
            is_active_set,
        )

    async def assign_employee(self, geofence_id: uuid.UUID, employee_id: uuid.UUID) -> None:
        if await self._repo.get_by_id(geofence_id) is None:
            raise GeofenceNotFoundError(f"geofence {geofence_id} not found")
        if await self._employees.get_by_id(employee_id) is None:
            raise EmployeeNotFoundError(f"employee {employee_id} not found")
        await self._repo.assign_employee(geofence_id, employee_id)

    async def unassign_employee(self, geofence_id: uuid.UUID, employee_id: uuid.UUID) -> None:
        if await self._repo.get_by_id(geofence_id) is None:
            raise GeofenceNotFoundError(f"geofence {geofence_id} not found")
        await self._repo.unassign_employee(geofence_id, employee_id)

    async def list_assigned_employees(self, geofence_id: uuid.UUID) -> list[Employee]:
        if await self._repo.get_by_id(geofence_id) is None:
            raise GeofenceNotFoundError(f"geofence {geofence_id} not found")
        return await self._repo.list_assigned_employees(geofence_id)
