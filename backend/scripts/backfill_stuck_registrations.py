"""One-off backfill for accounts created during the self-signup migration
window (2026-08-12): before the "no email verification" fix, registrations
could get stuck unverified forever once the verify-email endpoint was
removed; before the "auto-create Employee profile" fix, verified
self-registrations had a User row but no Employee row (invisible in the HR
dashboard, 404 on check-in). Run once against the live dev DB to repair both
classes of already-created accounts. Safe to re-run (idempotent).
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import get_settings
from app.models.user import User
from app.services.employee_service import EmployeeService


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()

        unverified_fixed = []
        for user in users:
            if not user.is_verified:
                user.is_verified = True
                unverified_fixed.append(user.email)
        if unverified_fixed:
            await session.flush()

        employee_service = EmployeeService(session)
        profiles_created = []
        for user in users:
            await session.refresh(user, attribute_names=["role"])
            if user.role.name != "employee":
                continue
            employee = await employee_service.get_or_create_own_profile(user)
            if employee is not None:
                profiles_created.append((user.email, employee.employee_code))

        await session.commit()

    print(f"Verified {len(unverified_fixed)} stuck account(s): {unverified_fixed}")
    print(f"Employee profiles ensured for {len(profiles_created)} account(s):")
    for email, code in profiles_created:
        print(f"  {code}  {email}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
