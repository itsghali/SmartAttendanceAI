import logging
import uuid

import pytest
from sqlalchemy import select

from app.models.role import Role
from app.models.user import User
from tests.conftest import register_and_verify as _register_and_verify


async def _login(client, email: str, password: str = "Password123") -> str:
    resp = await client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _promote_to_admin(db_session, email: str) -> None:
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    admin_role = (await db_session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    user.role_id = admin_role.id
    await db_session.flush()


@pytest.mark.asyncio
async def test_employee_cannot_manage_other_users_devices(
    client, db_session, caplog, unique_email
):
    caplog.set_level(logging.INFO, logger="app.email")
    await _register_and_verify(client, caplog, unique_email)
    access_token = await _login(client, unique_email)

    other_email = f"other-{unique_email}"
    await _register_and_verify(client, caplog, other_email)
    other_login = await client.post(
        "/auth/login", json={"email": other_email, "password": "Password123"}
    )
    other_user_id = (
        await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {other_login.json()['access_token']}"},
        )
    ).json()["id"]

    resp = await client.get(
        f"/users/{other_user_id}/devices",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_manage_other_users_devices(client, db_session, caplog, unique_email):
    caplog.set_level(logging.INFO, logger="app.email")
    await _register_and_verify(client, caplog, unique_email)
    login = await client.post(
        "/auth/login",
        json={
            "email": unique_email,
            "password": "Password123",
            "device_identifier": "target-device",
        },
    )
    target_access = login.json()["access_token"]
    target_user_id = (
        await client.get("/auth/me", headers={"Authorization": f"Bearer {target_access}"})
    ).json()["id"]

    admin_email = f"admin-{unique_email}"
    await _register_and_verify(client, caplog, admin_email)
    await _promote_to_admin(db_session, admin_email)
    admin_access = await _login(client, admin_email)

    resp = await client.get(
        f"/users/{target_user_id}/devices",
        headers={"Authorization": f"Bearer {admin_access}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_unknown_permission_denied_for_employee(client, caplog, unique_email):
    caplog.set_level(logging.INFO, logger="app.email")
    await _register_and_verify(client, caplog, unique_email)
    access_token = await _login(client, unique_email)

    resp = await client.get(
        f"/users/{uuid.uuid4()}/sessions",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 403
