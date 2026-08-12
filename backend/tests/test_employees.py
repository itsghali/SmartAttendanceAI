import logging
import uuid

import pytest

from tests.conftest import login, promote_to_role, register_and_verify


async def _make_hr_manager(client, db_session, caplog, email: str) -> str:
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, email)
    await promote_to_role(db_session, email, "hr_manager")
    return await login(client, email)


async def _create_department(client, headers, name: str) -> str:
    resp = await client.post("/departments", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _employee_payload(email: str, **overrides) -> dict:
    payload = {
        "email": email,
        "full_name": "New Hire",
        "password": "TempPass123",
        "hire_date": "2026-01-15",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_hr_can_onboard_employee_and_otp_is_issued(
    client, db_session, caplog, unique_email
):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {hr_access}"}
    dept_id = await _create_department(client, headers, "Engineering")

    new_hire_email = f"hire-{unique_email}"
    caplog.clear()
    resp = await client.post(
        "/employees",
        json=_employee_payload(new_hire_email, department_id=dept_id, job_title="Engineer"),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["employee_code"].startswith("EMP-")
    assert body["user"]["email"] == new_hire_email
    assert body["user"]["is_verified"] is True
    assert body["department_id"] == dept_id
    assert body["status"] == "active"
    assert "verification code is" in caplog.text  # password-reset OTP was issued


@pytest.mark.asyncio
async def test_onboard_duplicate_email_rejected(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {hr_access}"}

    resp = await client.post(
        "/employees", json=_employee_payload(unique_email), headers=headers
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_onboard_unknown_role_rejected(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {hr_access}"}

    resp = await client.post(
        "/employees",
        json=_employee_payload(f"hire-{unique_email}", role_name="not_a_real_role"),
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_onboard_invalid_department_rejected(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {hr_access}"}

    resp = await client.post(
        "/employees",
        json=_employee_payload(f"hire-{unique_email}", department_id=str(uuid.uuid4())),
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_employees_filtered_by_department(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {hr_access}"}
    eng_id = await _create_department(client, headers, "Engineering")
    sales_id = await _create_department(client, headers, "Sales")

    await client.post(
        "/employees",
        json=_employee_payload(f"eng-{unique_email}", department_id=eng_id),
        headers=headers,
    )
    await client.post(
        "/employees",
        json=_employee_payload(f"sales-{unique_email}", department_id=sales_id),
        headers=headers,
    )

    all_employees = await client.get("/employees", headers=headers)
    assert all_employees.status_code == 200
    # 2 onboarded below + the HR bootstrap account itself: it self-registered
    # via /auth/register (auto-creates an Employee row) before being promoted
    # to hr_manager, and promotion doesn't remove that row — see
    # AuthService.register / EmployeeService.get_or_create_own_profile.
    assert all_employees.json()["total"] == 3

    eng_only = await client.get(f"/employees?department_id={eng_id}", headers=headers)
    assert eng_only.status_code == 200
    assert eng_only.json()["total"] == 1
    assert eng_only.json()["items"][0]["department_id"] == eng_id


@pytest.mark.asyncio
async def test_get_my_employee_profile(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {hr_access}"}

    new_hire_email = f"hire-{unique_email}"
    await client.post(
        "/employees", json=_employee_payload(new_hire_email), headers=headers
    )

    employee_access = await login(client, new_hire_email, password="TempPass123")
    resp = await client.get(
        "/employees/me", headers={"Authorization": f"Bearer {employee_access}"}
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == new_hire_email


@pytest.mark.asyncio
async def test_self_registered_employee_has_profile_and_appears_in_hr_list(
    client, db_session, caplog, unique_email
):
    # Mobile-style self-signup (no role) — must get an Employee row immediately,
    # not just on first attendance action, so HR sees them in the dashboard
    # right away.
    resp = await client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": "Password123",
            "full_name": "Self Signup",
            "phone_number": "+15551230000",
        },
    )
    assert resp.status_code == 201, resp.text

    access = await login(client, unique_email, password="Password123")
    me = await client.get("/employees/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["user"]["email"] == unique_email
    assert body["phone_number"] == "+15551230000"
    assert body["employee_code"].startswith("EMP-")

    hr_access = await _make_hr_manager(client, db_session, caplog, f"hr-{unique_email}")
    listing = await client.get(
        "/employees", headers={"Authorization": f"Bearer {hr_access}"}
    )
    assert listing.status_code == 200
    emails = [e["user"]["email"] for e in listing.json()["items"]]
    assert unique_email in emails


@pytest.mark.asyncio
async def test_privileged_signup_does_not_get_employee_profile(
    client, unique_email, monkeypatch
):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.services.auth_service.get_settings",
        lambda: SimpleNamespace(admin_signup_code="correct-code"),
    )
    resp = await client.post(
        "/auth/register",
        json={
            "email": unique_email,
            "password": "Password123",
            "full_name": "Admin Signup",
            "role": "admin",
            "setup_code": "correct-code",
        },
    )
    assert resp.status_code == 201, resp.text

    access = await login(client, unique_email, password="Password123")
    me = await client.get("/employees/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 404


@pytest.mark.asyncio
async def test_update_employee_department_and_self_supervision_rejected(
    client, db_session, caplog, unique_email
):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {hr_access}"}
    dept_id = await _create_department(client, headers, "Engineering")

    created = await client.post(
        "/employees", json=_employee_payload(f"hire-{unique_email}"), headers=headers
    )
    employee_id = created.json()["id"]

    updated = await client.patch(
        f"/employees/{employee_id}",
        json={"department_id": dept_id, "job_title": "Senior Engineer"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["department_id"] == dept_id
    assert updated.json()["job_title"] == "Senior Engineer"

    self_supervise = await client.patch(
        f"/employees/{employee_id}",
        json={"supervisor_id": employee_id},
        headers=headers,
    )
    assert self_supervise.status_code == 400


@pytest.mark.asyncio
async def test_terminate_employee_deactivates_login(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {hr_access}"}

    new_hire_email = f"hire-{unique_email}"
    created = await client.post(
        "/employees", json=_employee_payload(new_hire_email), headers=headers
    )
    employee_id = created.json()["id"]

    terminated = await client.patch(
        f"/employees/{employee_id}/status",
        json={"status": "terminated"},
        headers=headers,
    )
    assert terminated.status_code == 200
    assert terminated.json()["status"] == "terminated"
    assert terminated.json()["user"]["is_active"] is False

    login_attempt = await client.post(
        "/auth/login", json={"email": new_hire_email, "password": "TempPass123"}
    )
    assert login_attempt.status_code == 403


@pytest.mark.asyncio
async def test_employee_role_cannot_list_employees(client, caplog, unique_email):
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, unique_email)
    access = await login(client, unique_email)

    resp = await client.get(
        "/employees", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 403
