import logging
import uuid

import pytest

from tests.conftest import login, promote_to_role, register_and_verify


async def _make_role(client, db_session, caplog, email: str, role_name: str) -> str:
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, email)
    await promote_to_role(db_session, email, role_name)
    return await login(client, email)


async def _make_admin(client, db_session, caplog, email: str) -> str:
    return await _make_role(client, db_session, caplog, email, "admin")


def _geofence_payload(**overrides) -> dict:
    payload = {
        "name": "HQ",
        "center_latitude": 36.8065,
        "center_longitude": 10.1815,
        "radius_meters": 100,
    }
    payload.update(overrides)
    return payload


_POLYGON_POINTS = [
    {"latitude": 36.80, "longitude": 10.18},
    {"latitude": 36.80, "longitude": 10.19},
    {"latitude": 36.81, "longitude": 10.19},
    {"latitude": 36.81, "longitude": 10.18},
]


def _polygon_payload(**overrides) -> dict:
    payload = {
        "name": "Chantier A",
        "boundary_type": "polygon",
        "polygon_points": _POLYGON_POINTS,
    }
    payload.update(overrides)
    return payload


async def _onboard_employee(client, headers, email: str, **overrides) -> dict:
    payload = {
        "email": email,
        "full_name": "Geofence Test Employee",
        "password": "TempPass123",
        "hire_date": "2026-01-15",
    }
    payload.update(overrides)
    resp = await client.post("/employees", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_admin_can_create_geofence(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    resp = await client.post(
        "/geofences", json=_geofence_payload(), headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "HQ"
    assert body["is_active"] is True
    assert body["department_id"] is None


@pytest.mark.asyncio
async def test_employee_cannot_create_geofence(client, caplog, unique_email):
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, unique_email)
    access = await login(client, unique_email)

    resp = await client.post(
        "/geofences", json=_geofence_payload(), headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_geofences_filters_by_department(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}

    dept = await client.post("/departments", json={"name": "Eng"}, headers=headers)
    dept_id = dept.json()["id"]

    await client.post(
        "/geofences", json=_geofence_payload(name="Global"), headers=headers
    )
    await client.post(
        "/geofences",
        json=_geofence_payload(name="Eng HQ", department_id=dept_id),
        headers=headers,
    )

    all_geofences = await client.get("/geofences", headers=headers)
    assert all_geofences.status_code == 200
    assert all_geofences.json()["total"] == 2

    dept_only = await client.get(f"/geofences?department_id={dept_id}", headers=headers)
    assert dept_only.json()["total"] == 1
    assert dept_only.json()["items"][0]["name"] == "Eng HQ"


@pytest.mark.asyncio
async def test_list_geofences_filters_by_is_active(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}

    created = await client.post("/geofences", json=_geofence_payload(), headers=headers)
    geofence_id = created.json()["id"]
    await client.patch(f"/geofences/{geofence_id}", json={"is_active": False}, headers=headers)

    active_only = await client.get("/geofences?is_active=true", headers=headers)
    assert active_only.json()["total"] == 0

    inactive_only = await client.get("/geofences?is_active=false", headers=headers)
    assert inactive_only.json()["total"] == 1


@pytest.mark.asyncio
async def test_get_unknown_geofence_404(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    resp = await client.get(
        f"/geofences/{uuid.uuid4()}", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_updates_fields_and_toggles_active(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}

    created = await client.post("/geofences", json=_geofence_payload(), headers=headers)
    geofence_id = created.json()["id"]

    updated = await client.patch(
        f"/geofences/{geofence_id}",
        json={"radius_meters": 250, "is_active": False},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["radius_meters"] == 250
    assert updated.json()["is_active"] is False


@pytest.mark.asyncio
async def test_patch_unknown_department_rejected(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}

    created = await client.post("/geofences", json=_geofence_payload(), headers=headers)
    geofence_id = created.json()["id"]

    resp = await client.patch(
        f"/geofences/{geofence_id}",
        json={"department_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_auditor_can_read_but_not_write(client, db_session, caplog, unique_email):
    admin_access = await _make_admin(client, db_session, caplog, unique_email)
    created = await client.post(
        "/geofences", json=_geofence_payload(), headers={"Authorization": f"Bearer {admin_access}"}
    )
    geofence_id = created.json()["id"]

    auditor_email = f"auditor-{unique_email}"
    auditor_access = await _make_role(client, db_session, caplog, auditor_email, "auditor")
    auditor_headers = {"Authorization": f"Bearer {auditor_access}"}

    read_list = await client.get("/geofences", headers=auditor_headers)
    assert read_list.status_code == 200
    read_one = await client.get(f"/geofences/{geofence_id}", headers=auditor_headers)
    assert read_one.status_code == 200

    write_attempt = await client.post(
        "/geofences", json=_geofence_payload(), headers=auditor_headers
    )
    assert write_attempt.status_code == 403

    patch_attempt = await client.patch(
        f"/geofences/{geofence_id}", json={"is_active": False}, headers=auditor_headers
    )
    assert patch_attempt.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_polygon_geofence(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    resp = await client.post(
        "/geofences", json=_polygon_payload(), headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["boundary_type"] == "polygon"
    assert body["polygon_points"] == _POLYGON_POINTS
    assert body["center_latitude"] is None
    assert body["radius_meters"] is None


@pytest.mark.asyncio
async def test_polygon_geofence_rejects_too_few_points(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    resp = await client.post(
        "/geofences",
        json=_polygon_payload(polygon_points=_POLYGON_POINTS[:2]),
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_circle_geofence_rejects_missing_radius(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    resp = await client.post(
        "/geofences",
        json={"name": "Bad Circle", "center_latitude": 36.8, "center_longitude": 10.18},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_can_convert_circle_to_polygon(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}
    created = await client.post("/geofences", json=_geofence_payload(), headers=headers)
    geofence_id = created.json()["id"]

    resp = await client.patch(
        f"/geofences/{geofence_id}",
        json={"boundary_type": "polygon", "polygon_points": _POLYGON_POINTS},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["boundary_type"] == "polygon"

    # dropping the polygon points afterward without also going back to circle
    # fields is invalid — the site would have no usable boundary
    bad = await client.patch(
        f"/geofences/{geofence_id}", json={"polygon_points": None}, headers=headers
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_assign_and_unassign_employee_to_geofence(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}
    created = await client.post("/geofences", json=_polygon_payload(), headers=headers)
    geofence_id = created.json()["id"]
    employee = await _onboard_employee(client, headers, f"assignee-{unique_email}")
    employee_id = employee["id"]

    assign = await client.post(
        f"/geofences/{geofence_id}/employees/{employee_id}", headers=headers
    )
    assert assign.status_code == 204

    # idempotent re-assign
    assign_again = await client.post(
        f"/geofences/{geofence_id}/employees/{employee_id}", headers=headers
    )
    assert assign_again.status_code == 204

    listed = await client.get(f"/geofences/{geofence_id}/employees", headers=headers)
    assert listed.status_code == 200
    assert [e["id"] for e in listed.json()["items"]] == [employee_id]
    assert listed.json()["items"][0]["full_name"] == "Geofence Test Employee"

    unassign = await client.delete(
        f"/geofences/{geofence_id}/employees/{employee_id}", headers=headers
    )
    assert unassign.status_code == 204

    listed_after = await client.get(f"/geofences/{geofence_id}/employees", headers=headers)
    assert listed_after.json()["items"] == []


@pytest.mark.asyncio
async def test_assign_unknown_employee_404(client, db_session, caplog, unique_email):
    access = await _make_admin(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {access}"}
    created = await client.post("/geofences", json=_polygon_payload(), headers=headers)
    geofence_id = created.json()["id"]

    resp = await client.post(
        f"/geofences/{geofence_id}/employees/{uuid.uuid4()}", headers=headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_employee_cannot_assign_geofence(client, db_session, caplog, unique_email):
    admin_access = await _make_admin(client, db_session, caplog, unique_email)
    admin_headers = {"Authorization": f"Bearer {admin_access}"}
    created = await client.post("/geofences", json=_polygon_payload(), headers=admin_headers)
    geofence_id = created.json()["id"]
    employee = await _onboard_employee(client, admin_headers, f"target-{unique_email}")

    employee_email = f"caller-{unique_email}"
    await register_and_verify(client, caplog, employee_email)
    employee_access = await login(client, employee_email)

    resp = await client.post(
        f"/geofences/{geofence_id}/employees/{employee['id']}",
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 403
