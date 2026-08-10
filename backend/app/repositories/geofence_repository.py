import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.employee_geofence import EmployeeGeofence
from app.models.geofence import Geofence, GeofenceBoundaryType


class GeofenceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

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
        geofence = Geofence(
            name=name,
            department_id=department_id,
            boundary_type=boundary_type,
            center_latitude=center_latitude,
            center_longitude=center_longitude,
            radius_meters=radius_meters,
            polygon_points=polygon_points,
        )
        self._session.add(geofence)
        await self._session.flush()
        return geofence

    async def get_by_id(self, geofence_id: uuid.UUID) -> Geofence | None:
        stmt = select(Geofence).where(Geofence.id == geofence_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_paginated(
        self, department_id: uuid.UUID | None, is_active: bool | None, limit: int, offset: int
    ) -> tuple[list[Geofence], int]:
        stmt = select(Geofence)
        count_stmt = select(func.count()).select_from(Geofence)
        if department_id is not None:
            stmt = stmt.where(Geofence.department_id == department_id)
            count_stmt = count_stmt.where(Geofence.department_id == department_id)
        if is_active is not None:
            stmt = stmt.where(Geofence.is_active == is_active)
            count_stmt = count_stmt.where(Geofence.is_active == is_active)

        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(Geofence.name).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_active_for_employee(
        self, employee_id: uuid.UUID, department_id: uuid.UUID | None
    ) -> list[Geofence]:
        """Union of department/global-scoped geofences and geofences HR has
        explicitly assigned to this employee — either grants access."""
        dept_stmt = select(Geofence).where(
            Geofence.is_active.is_(True),
            or_(Geofence.department_id == department_id, Geofence.department_id.is_(None)),
        )
        assigned_stmt = (
            select(Geofence)
            .join(EmployeeGeofence, EmployeeGeofence.geofence_id == Geofence.id)
            .where(Geofence.is_active.is_(True), EmployeeGeofence.employee_id == employee_id)
        )
        dept_result = await self._session.execute(dept_stmt)
        assigned_result = await self._session.execute(assigned_stmt)
        by_id = {g.id: g for g in dept_result.scalars().all()}
        for g in assigned_result.scalars().all():
            by_id[g.id] = g
        return list(by_id.values())

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
        if name is not None:
            geofence.name = name
        if department_id_set:
            geofence.department_id = department_id
        if boundary_type is not None:
            geofence.boundary_type = boundary_type
        if center_latitude_set:
            geofence.center_latitude = center_latitude
        if center_longitude_set:
            geofence.center_longitude = center_longitude
        if radius_meters_set:
            geofence.radius_meters = radius_meters
        if polygon_points_set:
            geofence.polygon_points = polygon_points
        if is_active_set:
            geofence.is_active = is_active
        await self._session.flush()

    async def assign_employee(self, geofence_id: uuid.UUID, employee_id: uuid.UUID) -> None:
        exists_stmt = select(EmployeeGeofence).where(
            EmployeeGeofence.geofence_id == geofence_id,
            EmployeeGeofence.employee_id == employee_id,
        )
        existing = (await self._session.execute(exists_stmt)).scalars().first()
        if existing is not None:
            return
        self._session.add(EmployeeGeofence(geofence_id=geofence_id, employee_id=employee_id))
        await self._session.flush()

    async def unassign_employee(self, geofence_id: uuid.UUID, employee_id: uuid.UUID) -> None:
        stmt = select(EmployeeGeofence).where(
            EmployeeGeofence.geofence_id == geofence_id,
            EmployeeGeofence.employee_id == employee_id,
        )
        existing = (await self._session.execute(stmt)).scalars().first()
        if existing is not None:
            await self._session.delete(existing)
            await self._session.flush()

    async def list_assigned_employees(self, geofence_id: uuid.UUID) -> list[Employee]:
        stmt = (
            select(Employee)
            .options(selectinload(Employee.user))
            .join(EmployeeGeofence, EmployeeGeofence.employee_id == Employee.id)
            .where(EmployeeGeofence.geofence_id == geofence_id)
            .order_by(Employee.employee_code)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
