"""Run: python -m scripts.seed_rbac (from backend/, with venv active and DB reachable)."""

import asyncio

from app.core.database import async_session_factory
from app.core.seed import seed_rbac


async def main() -> None:
    async with async_session_factory() as session:
        await seed_rbac(session)
    print("RBAC seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
