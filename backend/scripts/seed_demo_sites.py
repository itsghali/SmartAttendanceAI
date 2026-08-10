"""Seed demo departments, geofences, and employee site assignments.

Run from `backend/` with the backend virtualenv active:

    python -m scripts.seed_demo_sites
"""

import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.department import Department
from app.models.employee import Employee
from app.models.geofence import Geofence
from app.models.user import User

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:55432/smartattendance"

CASABLANCA = {
    "department": "Casablanca Demo Dept",
    "geofence": "Casablanca Demo Site",
    "latitude": 33.5897222222,
    "longitude": -7.6038888889,
}
MARRAKECH = {
    "department": "Marrakech Demo Dept",
    "geofence": "Marrakech Demo Site",
    "latitude": 31.6286111111,
    "longitude": -7.9919444444,
}


def read_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


async def upsert_department(session, name: str) -> Department:
    result = await session.execute(select(Department).where(Department.name == name))
    department = result.scalars().first()
    if department is None:
        department = Department(name=name, description="")
        session.add(department)
    return department


async def upsert_geofence(
    session,
    name: str,
    department: Department,
    latitude: float,
    longitude: float,
) -> Geofence:
    result = await session.execute(select(Geofence).where(Geofence.name == name))
    geofence = result.scalars().first()
    if geofence is None:
        geofence = Geofence(
            name=name,
            department_id=department.id,
            center_latitude=latitude,
            center_longitude=longitude,
            radius_meters=100.0,
            is_active=True,
        )
        session.add(geofence)
    else:
        geofence.department_id = department.id
        geofence.center_latitude = latitude
        geofence.center_longitude = longitude
        geofence.radius_meters = 100.0
        geofence.is_active = True
    return geofence


async def assign_employee_to_department(session, email: str, department: Department) -> bool:
    user_result = await session.execute(select(User).where(User.email == email))
    user = user_result.scalars().first()
    if user is None:
        print(f"missing user: {email}")
        return False

    employee_result = await session.execute(select(Employee).where(Employee.user_id == user.id))
    employee = employee_result.scalars().first()
    if employee is None:
        print(f"missing employee profile: {email}")
        return False

    employee.department_id = department.id
    return True


async def main() -> None:
    engine = create_async_engine(read_database_url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        casa_dept = await upsert_department(session, CASABLANCA["department"])
        marrakech_dept = await upsert_department(session, MARRAKECH["department"])
        await session.flush()

        await upsert_geofence(
            session,
            CASABLANCA["geofence"],
            casa_dept,
            CASABLANCA["latitude"],
            CASABLANCA["longitude"],
        )
        await upsert_geofence(
            session,
            MARRAKECH["geofence"],
            marrakech_dept,
            MARRAKECH["latitude"],
            MARRAKECH["longitude"],
        )

        demo_updated = await assign_employee_to_department(session, "demo@example.com", marrakech_dept)
        casa_updated = await assign_employee_to_department(session, "casa@example.com", casa_dept)

        await session.commit()

    await engine.dispose()

    print("seeded Casablanca Demo Site")
    print("seeded Marrakech Demo Site")
    if demo_updated:
        print("assigned demo@example.com to Marrakech Demo Dept")
    if casa_updated:
        print("assigned casa@example.com to Casablanca Demo Dept")


if __name__ == "__main__":
    asyncio.run(main())
