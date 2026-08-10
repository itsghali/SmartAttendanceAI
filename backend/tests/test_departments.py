import logging

import pytest

from tests.conftest import login, promote_to_role, register_and_verify


async def _make_admin(client, db_session, caplog, email: str) -> str:
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, email)
    await promote_to_role(db_session, email, "admin")
    return await login(client, email)


@pytest.mark.asyncio
async def test_admin_can_create_list_and_get_department(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}

    created = await client.post(
        "/departments",
        json={"name": "Engineering", "description": "Builds the product"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    dept_id = created.json()["id"]

    listed = await client.get("/departments", headers=headers)
    assert listed.status_code == 200
    assert any(d["id"] == dept_id for d in listed.json())

    fetched = await client.get(f"/departments/{dept_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Engineering"


@pytest.mark.asyncio
async def test_employee_cannot_create_department(client, caplog, unique_email):
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, unique_email)
    access = await login(client, unique_email)

    resp = await client.post(
        "/departments",
        json={"name": "Engineering"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_department_name_rejected(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}

    payload = {"name": "Sales"}
    first = await client.post("/departments", json=payload, headers=headers)
    assert first.status_code == 201
    second = await client.post("/departments", json=payload, headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_update_and_delete_department(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}

    created = await client.post("/departments", json={"name": "Support"}, headers=headers)
    dept_id = created.json()["id"]

    updated = await client.patch(
        f"/departments/{dept_id}",
        json={"description": "Handles customer issues"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Handles customer issues"
    assert updated.json()["name"] == "Support"

    deleted = await client.delete(f"/departments/{dept_id}", headers=headers)
    assert deleted.status_code == 204

    missing = await client.get(f"/departments/{dept_id}", headers=headers)
    assert missing.status_code == 404
