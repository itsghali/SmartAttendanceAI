"""Create a pre-verified demo login user (idempotent).

Run: python -m scripts.seed_demo_user <email> <password> <full_name> <role_name>
Defaults: hr@example.com / Hr12345678 / "HR Manager" / hr_manager

Requires roles to already be seeded (run scripts.seed_rbac first).
Bypasses email/OTP verification — for demo/seed data only, not a
registration flow substitute.
"""

import asyncio
import sys

from app.core.database import async_session_factory
from app.core.security import hash_password
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository


async def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "hr@example.com"
    password = sys.argv[2] if len(sys.argv) > 2 else "Hr12345678"
    full_name = sys.argv[3] if len(sys.argv) > 3 else "HR Manager"
    role_name = sys.argv[4] if len(sys.argv) > 4 else "hr_manager"

    async with async_session_factory() as session:
        users = UserRepository(session)
        roles = RoleRepository(session)

        existing = await users.get_by_email(email)
        if existing is not None:
            print(f"User {email} already exists (id={existing.id}). No changes made.")
            return

        role = await roles.get_by_name(role_name)
        if role is None:
            raise RuntimeError(f"role '{role_name}' is not seeded — run scripts.seed_rbac first")

        user = await users.create(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role_id=role.id,
        )
        await users.mark_verified(user)
        await session.commit()
        print(f"Created user {email} (id={user.id}, role={role_name}, verified=True).")


if __name__ == "__main__":
    asyncio.run(main())
