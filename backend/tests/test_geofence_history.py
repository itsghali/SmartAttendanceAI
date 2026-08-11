import logging
import uuid

import pytest
from sqlalchemy import select

from app.config.settings import get_settings
from app.models.geofence import Geofence
from app.models.geofence_event import GeofenceEventType
from app.repositories.geofence_event_repository import GeofenceEventRepository
from tests.conftest import login, promote_to_role, register_and_verify

OFFICE_LAT = 36.8065
OFFICE_LNG = 10.1815
FAR_LAT = 36.82


@pytest.fixture(autouse=True)
def _face_verification_off(monkeypatch):
    """This dev machine's backend/.env sets FACE_VERIFICATION_ENABLED=true
    (left on from the face module's own tests) — irrelevant to what this
    file verifies (geofence-event history/exceptions endpoints), so turn it
    off rather than fabricate selfie payloads in every setup helper here."""
    monkeypatch.setattr(get_settings(), "face_verification_enabled", False)


async def _make_role(client, db_session, caplog, email: str, role_name: str) -> str:
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, email)
    await promote_to_role(db_session, email, role_name)
    return await login(client, email)


async def _setup_checked_in_employee(client, db_session, caplog, unique_email):
    """HR onboards + geofences an employee, employee checks in. Returns
    (hr_headers, employee_id, attendance_id, geofence_id)."""
    hr_access = await _make_role(client, db_session, caplog, unique_email, "hr_manager")
    hr_headers = {"Authorization": f"Bearer {hr_access}"}

    geofence_resp = await client.post(
        "/geofences",
        json={
            "name": "HQ",
            "center_latitude": OFFICE_LAT,
            "center_longitude": OFFICE_LNG,
            "radius_meters": 100,
        },
        headers=hr_headers,
    )
    assert geofence_resp.status_code == 201, geofence_resp.text
    geofence_id = geofence_resp.json()["id"]

    hire_email = f"hire-{unique_email}"
    employee_resp = await client.post(
        "/employees",
        json={
            "email": hire_email,
            "full_name": "Geofence History Employee",
            "password": "TempPass123",
            "hire_date": "2026-01-15",
        },
        headers=hr_headers,
    )
    assert employee_resp.status_code == 201, employee_resp.text
    employee_id = employee_resp.json()["id"]

    employee_access = await login(client, hire_email, password="TempPass123")
    checkin_resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert checkin_resp.status_code == 201, checkin_resp.text
    attendance_id = checkin_resp.json()["id"]

    return hr_headers, employee_id, attendance_id, geofence_id


@pytest.mark.asyncio
async def test_exceptions_list_shows_checked_in_employee_with_no_coords(
    client, db_session, caplog, unique_email
):
    hr_headers, employee_id, _, _ = await _setup_checked_in_employee(
        client, db_session, caplog, unique_email
    )

    resp = await client.get("/attendance/exceptions", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["needs_attention_count"] == 0
    row = body["items"][0]
    assert row["employee_id"] == employee_id
    assert row["employee_full_name"] == "Geofence History Employee"
    assert row["monitoring_status"] in ("live", "stale")
    assert row["needs_attention"] is False
    assert "latitude" not in row
    assert "longitude" not in row


@pytest.mark.asyncio
async def test_exceptions_list_flags_employee_with_open_exit(
    client, db_session, caplog, unique_email
):
    hr_headers, employee_id, attendance_id, geofence_id = await _setup_checked_in_employee(
        client, db_session, caplog, unique_email
    )
    await GeofenceEventRepository(db_session).create(
        uuid.UUID(employee_id),
        uuid.UUID(attendance_id),
        uuid.UUID(geofence_id),
        GeofenceEventType.EXIT,
        FAR_LAT,
        OFFICE_LNG,
    )
    await db_session.commit()

    resp = await client.get("/attendance/exceptions", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_attention_count"] == 1
    assert body["items"][0]["needs_attention"] is True


@pytest.mark.asyncio
async def test_history_returns_event_summary_without_coords_and_with_geofence_name(
    client, db_session, caplog, unique_email
):
    hr_headers, employee_id, attendance_id, geofence_id = await _setup_checked_in_employee(
        client, db_session, caplog, unique_email
    )
    await GeofenceEventRepository(db_session).create(
        uuid.UUID(employee_id), uuid.UUID(attendance_id), uuid.UUID(geofence_id),
        GeofenceEventType.EXIT, 36.82, OFFICE_LNG,
    )
    await db_session.commit()

    resp = await client.get(f"/attendance/{employee_id}/history", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 3, not 1: check-in itself fires an ENTER event (attendance_service.py)
    # and the check-in itself is now merged into this timeline too, in
    # addition to the EXIT this test adds manually.
    assert body["total"] == 3
    row = body["items"][0]  # newest first (created_at desc) -> the EXIT
    assert row["event_type"] == "exit"
    assert row["geofence_name"] == "HQ"
    assert "latitude" not in row
    assert "longitude" not in row
    event_types = {item["event_type"] for item in body["items"]}
    assert event_types == {"exit", "enter", "check_in"}


@pytest.mark.asyncio
async def test_history_shows_deleted_geofence_fallback_label(
    client, db_session, caplog, unique_email
):
    hr_headers, employee_id, attendance_id, geofence_id = await _setup_checked_in_employee(
        client, db_session, caplog, unique_email
    )
    # No hard-delete endpoint exists on /geofences yet — deleting the row
    # directly mirrors what ON DELETE SET NULL models in production (the
    # column stays a dangling reference in this SQLite test since FK
    # enforcement isn't turned on here, but the ORM relationship still
    # resolves to None for a row that no longer exists, same as production).
    geofence = (
        await db_session.execute(select(Geofence).where(Geofence.id == uuid.UUID(geofence_id)))
    ).scalar_one()
    await db_session.delete(geofence)
    await db_session.commit()

    resp = await client.get(f"/attendance/{employee_id}/history", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"][0]["geofence_name"] == "Deleted geofence"


@pytest.mark.asyncio
async def test_history_pagination_respects_limit_and_offset(
    client, db_session, caplog, unique_email
):
    hr_headers, employee_id, attendance_id, geofence_id = await _setup_checked_in_employee(
        client, db_session, caplog, unique_email
    )
    # check-in already fired 1 ENTER + is itself merged in as 1 check_in
    # entry; add 2 more geofence events -> 4 total.
    repo = GeofenceEventRepository(db_session)
    await repo.create(
        uuid.UUID(employee_id), uuid.UUID(attendance_id), uuid.UUID(geofence_id),
        GeofenceEventType.EXIT, FAR_LAT, OFFICE_LNG,
    )
    await repo.create(
        uuid.UUID(employee_id), uuid.UUID(attendance_id), uuid.UUID(geofence_id),
        GeofenceEventType.RETURN, OFFICE_LAT, OFFICE_LNG,
    )
    await db_session.commit()

    resp = await client.get(
        f"/attendance/{employee_id}/history", params={"limit": 2, "offset": 0}, headers=hr_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 4
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0

    resp = await client.get(
        f"/attendance/{employee_id}/history", params={"limit": 2, "offset": 2}, headers=hr_headers
    )
    body = resp.json()
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_history_includes_check_in_and_check_out_entries(
    client, db_session, caplog, unique_email
):
    hr_access = await _make_role(client, db_session, caplog, unique_email, "hr_manager")
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    geofence_resp = await client.post(
        "/geofences",
        json={
            "name": "HQ",
            "center_latitude": OFFICE_LAT,
            "center_longitude": OFFICE_LNG,
            "radius_meters": 100,
        },
        headers=hr_headers,
    )
    assert geofence_resp.status_code == 201, geofence_resp.text
    hire_email = f"hire-{unique_email}"
    employee_resp = await client.post(
        "/employees",
        json={
            "email": hire_email,
            "full_name": "Full Shift Employee",
            "password": "TempPass123",
            "hire_date": "2026-01-15",
        },
        headers=hr_headers,
    )
    assert employee_resp.status_code == 201, employee_resp.text
    employee_id = employee_resp.json()["id"]

    employee_access = await login(client, hire_email, password="TempPass123")
    employee_headers = {"Authorization": f"Bearer {employee_access}"}
    checkin_resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10},
        headers=employee_headers,
    )
    assert checkin_resp.status_code == 201, checkin_resp.text

    checkout_resp = await client.post(
        "/attendance/check-out",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10},
        headers=employee_headers,
    )
    assert checkout_resp.status_code == 200, checkout_resp.text

    resp = await client.get(f"/attendance/{employee_id}/history", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    event_types = [item["event_type"] for item in body["items"]]
    assert "check_in" in event_types
    assert "check_out" in event_types
    # check-out is the most recent thing that happened
    assert event_types[0] == "check_out"
    check_in_row = next(i for i in body["items"] if i["event_type"] == "check_in")
    check_out_row = next(i for i in body["items"] if i["event_type"] == "check_out")
    assert check_in_row["geofence_name"] == "HQ"
    assert check_out_row["geofence_name"] == "HQ"
    assert check_in_row["id"] != check_out_row["id"]
    assert "latitude" not in check_in_row
    assert "longitude" not in check_out_row


@pytest.mark.asyncio
async def test_history_empty_for_employee_with_no_events(client, db_session, caplog, unique_email):
    hr_access = await _make_role(client, db_session, caplog, unique_email, "hr_manager")
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    hire_email = f"hire-{unique_email}"
    employee_resp = await client.post(
        "/employees",
        json={
            "email": hire_email,
            "full_name": "Never Checked In",
            "password": "TempPass123",
            "hire_date": "2026-01-15",
        },
        headers=hr_headers,
    )
    assert employee_resp.status_code == 201, employee_resp.text
    employee_id = employee_resp.json()["id"]

    resp = await client.get(f"/attendance/{employee_id}/history", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_exceptions_list_empty_when_no_one_checked_in(client, db_session, caplog, unique_email):
    hr_access = await _make_role(client, db_session, caplog, unique_email, "hr_manager")
    hr_headers = {"Authorization": f"Bearer {hr_access}"}

    resp = await client.get("/attendance/exceptions", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["needs_attention_count"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_exceptions_list_shows_not_monitored_for_manual_entry(
    client, db_session, caplog, unique_email
):
    """Manual/backfilled entries have no geofence to monitor against — the
    exceptions screen must show them in an honest "not monitored" state,
    never hide or crash on them (design doc success criteria)."""
    hr_access = await _make_role(client, db_session, caplog, unique_email, "hr_manager")
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    hire_email = f"hire-{unique_email}"
    employee_resp = await client.post(
        "/employees",
        json={
            "email": hire_email,
            "full_name": "Manual Entry Employee",
            "password": "TempPass123",
            "hire_date": "2026-01-15",
        },
        headers=hr_headers,
    )
    assert employee_resp.status_code == 201, employee_resp.text
    employee_id = employee_resp.json()["id"]

    manual_resp = await client.post(
        f"/attendance/{employee_id}/manual-entry",
        json={
            "attendance_date": "2026-08-11",
            "check_in_at": "2026-08-11T08:00:00Z",
            "status": "present",
        },
        headers=hr_headers,
    )
    assert manual_resp.status_code == 201, manual_resp.text
    assert manual_resp.json()["check_in_geofence_id"] is None

    resp = await client.get("/attendance/exceptions", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["monitoring_status"] == "not_monitored"
    assert row["needs_attention"] is False


@pytest.mark.asyncio
async def test_supervisor_cannot_access_exceptions_or_history(
    client, db_session, caplog, unique_email
):
    _, employee_id, _, _ = await _setup_checked_in_employee(client, db_session, caplog, unique_email)

    supervisor_email = f"supervisor-{unique_email}"
    supervisor_access = await _make_role(
        client, db_session, caplog, supervisor_email, "supervisor"
    )
    supervisor_headers = {"Authorization": f"Bearer {supervisor_access}"}

    resp = await client.get("/attendance/exceptions", headers=supervisor_headers)
    assert resp.status_code == 403, resp.text

    resp = await client.get(f"/attendance/{employee_id}/history", headers=supervisor_headers)
    assert resp.status_code == 403, resp.text
