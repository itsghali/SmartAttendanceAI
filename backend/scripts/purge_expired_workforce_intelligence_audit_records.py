"""Deletes rows older than GOVERNANCE.md Section 3's 12-month retention
window from the 4 append-only, unbounded-growth audit tables that hold real
-employee behavioral data: geofence_events, face_verification_attempts,
impossible_travel_rejections, employee_deviation_flags.

Deliberately NOT `synthetic_data_runs` (dev/bootstrap fixtures, not real
employee data — see GOVERNANCE.md's named boundary) or `employee_baselines`
(one row per employee, replaced in place on rebuild, nothing to purge).

Manual-trigger only, same as every other Workforce Intelligence batch job in
this codebase (no scheduler dependency). Run periodically by whoever
operates this deployment. Safe to re-run (a no-op once nothing is old
enough to qualify).
"""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import get_settings
from app.models.employee_deviation_flag import EmployeeDeviationFlag
from app.models.face_verification_attempt import FaceVerificationAttempt
from app.models.geofence_event import GeofenceEvent
from app.models.impossible_travel_rejection import ImpossibleTravelRejection
from app.models.mixins import utcnow

RETENTION = timedelta(days=365)

TABLES = (
    ("geofence_events", GeofenceEvent),
    ("face_verification_attempts", FaceVerificationAttempt),
    ("impossible_travel_rejections", ImpossibleTravelRejection),
    ("employee_deviation_flags", EmployeeDeviationFlag),
)


async def purge(session: AsyncSession, cutoff: datetime) -> dict[str, int]:
    """Pure-enough to unit test against any session (real Postgres or the
    test suite's SQLite fixture) — deliberately takes an already-open
    session rather than owning its own engine, so main() below is the only
    part of this module that needs a real database_url."""
    results: dict[str, int] = {}
    for name, model in TABLES:
        count_stmt = select(func.count()).select_from(model).where(model.created_at < cutoff)
        count = (await session.execute(count_stmt)).scalar_one()
        if count:
            await session.execute(delete(model).where(model.created_at < cutoff))
        results[name] = count
    await session.commit()
    return results


async def main() -> None:
    cutoff = utcnow() - RETENTION
    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        results = await purge(session, cutoff)
    await engine.dispose()

    print(f"Purged rows older than {cutoff.isoformat()} (12-month retention, GOVERNANCE.md):")
    for name, count in results.items():
        print(f"  {name}: {count} row(s) deleted")


if __name__ == "__main__":
    asyncio.run(main())
