"""Seed demo geofences for local manual testing.

Run from `backend/` with the virtualenv active and the database reachable:

    python -m scripts.seed_demo_geofence
"""

import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.geofence import Geofence


DEMO_GEOFENCES = (
    {
        "name": "Casablanca Demo Site",
        "center_latitude": 33.5897222222,
        "center_longitude": -7.6038888889,
        "radius_meters": 100.0,
    },
    {
        "name": "Marrakech Demo Site",
        "center_latitude": 31.6286111111,
        "center_longitude": -7.9919444444,
        "radius_meters": 100.0,
    },
)

DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:55432/smartattendance"


def read_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


async def main() -> None:
    engine = create_async_engine(read_database_url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        actions: list[str] = []
        for payload in DEMO_GEOFENCES:
            result = await session.execute(
                select(Geofence).where(Geofence.name == payload["name"])
            )
            geofence = result.scalars().first()

            if geofence is None:
                geofence = Geofence(
                    name=payload["name"],
                    department_id=None,
                    center_latitude=payload["center_latitude"],
                    center_longitude=payload["center_longitude"],
                    radius_meters=payload["radius_meters"],
                    is_active=True,
                )
                session.add(geofence)
                actions.append(f"created {payload['name']}")
            else:
                geofence.department_id = None
                geofence.center_latitude = payload["center_latitude"]
                geofence.center_longitude = payload["center_longitude"]
                geofence.radius_meters = payload["radius_meters"]
                geofence.is_active = True
                actions.append(f"updated {payload['name']}")

        await session.commit()
        for action in actions:
            print(action)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
