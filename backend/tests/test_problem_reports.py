import logging

import pytest

from tests.conftest import login, promote_to_role, register_and_verify


async def _make_role(client, db_session, caplog, email: str, role_name: str) -> str:
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, email)
    await promote_to_role(db_session, email, role_name)
    return await login(client, email)


async def _make_hr_manager(client, db_session, caplog, email: str) -> str:
    return await _make_role(client, db_session, caplog, email, "hr_manager")


async def _make_supervisor(client, db_session, caplog, email: str) -> str:
    return await _make_role(client, db_session, caplog, email, "supervisor")


async def _onboard_employee(client, headers, email: str, **overrides) -> dict:
    payload = {
        "email": email,
        "full_name": "Problem Report Test Employee",
        "password": "TempPass123",
        "hire_date": "2026-01-15",
    }
    payload.update(overrides)
    resp = await client.post("/employees", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _setup_employee(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    hire_email = f"hire-{unique_email}"
    employee = await _onboard_employee(client, hr_headers, hire_email)
    employee_access = await login(client, hire_email, password="TempPass123")
    return employee_access, employee, hr_headers


@pytest.mark.asyncio
async def test_employee_can_create_problem_report(client, db_session, caplog, unique_email):
    employee_access, employee, _ = await _setup_employee(client, db_session, caplog, unique_email)
    resp = await client.post(
        "/problem-reports",
        json={"message": "My check-in did not register this morning."},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["employee_id"] == employee["id"]
    assert body["employee_full_name"] == employee["user"]["full_name"]
    assert body["employee_code"] == employee["employee_code"]
    assert body["status"] == "open"
    assert body["resolved_at"] is None
    assert body["attendance_id"] is None


@pytest.mark.asyncio
async def test_employee_cannot_list_or_resolve_reports(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {employee_access}"}

    list_resp = await client.get("/problem-reports", headers=headers)
    assert list_resp.status_code == 403

    resolve_resp = await client.patch(
        "/problem-reports/00000000-0000-0000-0000-000000000000/resolve", headers=headers
    )
    assert resolve_resp.status_code == 403


@pytest.mark.asyncio
async def test_supervisor_cannot_list_reports(client, db_session, caplog, unique_email):
    # Deliberate scope choice (see AppHeader/audit follow-up): supervisor is
    # excluded from this feature in v1, same as it's already excluded from
    # geofence_events:read.
    supervisor_access = await _make_supervisor(client, db_session, caplog, unique_email)
    resp = await client.get(
        "/problem-reports", headers={"Authorization": f"Bearer {supervisor_access}"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_hr_can_list_filter_and_resolve_report(client, db_session, caplog, unique_email):
    employee_access, employee, hr_headers = await _setup_employee(
        client, db_session, caplog, unique_email
    )
    create_resp = await client.post(
        "/problem-reports",
        json={"message": "App crashed while checking out."},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    report_id = create_resp.json()["id"]

    open_resp = await client.get("/problem-reports?status=open", headers=hr_headers)
    assert open_resp.status_code == 200
    open_body = open_resp.json()
    assert any(r["id"] == report_id for r in open_body["items"])

    resolve_resp = await client.patch(f"/problem-reports/{report_id}/resolve", headers=hr_headers)
    assert resolve_resp.status_code == 200
    resolved_body = resolve_resp.json()
    assert resolved_body["status"] == "resolved"
    assert resolved_body["resolved_at"] is not None
    assert resolved_body["resolved_by_id"] is not None

    # Resolved reports drop out of the open filter.
    open_after_resp = await client.get("/problem-reports?status=open", headers=hr_headers)
    assert not any(r["id"] == report_id for r in open_after_resp.json()["items"])


@pytest.mark.asyncio
async def test_resolving_already_resolved_report_conflicts(
    client, db_session, caplog, unique_email
):
    employee_access, _, hr_headers = await _setup_employee(client, db_session, caplog, unique_email)
    create_resp = await client.post(
        "/problem-reports",
        json={"message": "Location permission kept failing."},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    report_id = create_resp.json()["id"]

    first = await client.patch(f"/problem-reports/{report_id}/resolve", headers=hr_headers)
    assert first.status_code == 200

    second = await client.patch(f"/problem-reports/{report_id}/resolve", headers=hr_headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_resolving_unknown_report_404s(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    resp = await client.patch(
        "/problem-reports/00000000-0000-0000-0000-000000000000/resolve",
        headers={"Authorization": f"Bearer {hr_access}"},
    )
    assert resp.status_code == 404
