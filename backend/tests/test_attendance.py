import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.attendance import Attendance, AttendanceStatus
from tests.conftest import login, promote_to_role, register_and_verify

OFFICE_LAT = 36.8065
OFFICE_LNG = 10.1815
# ~1.5km north of OFFICE — outside any reasonably-sized geofence
FAR_LAT = 36.82
FAR_LNG = 10.1815


async def _make_role(client, db_session, caplog, email: str, role_name: str) -> str:
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, email)
    await promote_to_role(db_session, email, role_name)
    return await login(client, email)


async def _make_hr_manager(client, db_session, caplog, email: str) -> str:
    return await _make_role(client, db_session, caplog, email, "hr_manager")


async def _make_admin(client, db_session, caplog, email: str) -> str:
    return await _make_role(client, db_session, caplog, email, "admin")


async def _create_geofence(client, headers, **overrides) -> str:
    payload = {
        "name": "HQ",
        "center_latitude": OFFICE_LAT,
        "center_longitude": OFFICE_LNG,
        "radius_meters": 100,
    }
    payload.update(overrides)
    resp = await client.post("/geofences", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _onboard_employee(client, headers, email: str, **overrides) -> dict:
    payload = {
        "email": email,
        "full_name": "Attendance Test Employee",
        "password": "TempPass123",
        "hire_date": "2026-01-15",
    }
    payload.update(overrides)
    resp = await client.post("/employees", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _setup_employee_with_geofence(client, db_session, caplog, unique_email):
    """HR onboards an employee under a department with an eligible geofence,
    returns (employee_access_token, employee_id)."""
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    await _create_geofence(client, hr_headers)  # global geofence, no department_id

    hire_email = f"hire-{unique_email}"
    employee = await _onboard_employee(client, hr_headers, hire_email)
    employee_access = await login(client, hire_email, password="TempPass123")
    return employee_access, employee["id"], hr_headers


@pytest.mark.asyncio
async def test_check_in_inside_geofence_succeeds(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}

    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "present"
    assert body["check_in_geofence_id"] is not None
    assert body["check_out_at"] is None


@pytest.mark.asyncio
async def test_check_in_outside_geofence_rejected(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}

    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": FAR_LAT, "longitude": FAR_LNG},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_check_in_with_no_geofence_configured_rejected(
    client, db_session, caplog, unique_email
):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    hire_email = f"hire-{unique_email}"
    await _onboard_employee(client, hr_headers, hire_email)
    employee_access = await login(client, hire_email, password="TempPass123")

    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_check_in_via_employee_assignment_without_department_match(
    client, db_session, caplog, unique_email
):
    """A geofence scoped to a department the employee isn't in is normally out
    of reach — HR assigning the employee directly to that specific site is
    what should unlock it."""
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}

    other_dept = await client.post("/departments", json={"name": "Other Dept"}, headers=hr_headers)
    other_dept_id = other_dept.json()["id"]
    geofence_id = await _create_geofence(client, hr_headers, department_id=other_dept_id)

    hire_email = f"hire-{unique_email}"
    employee = await _onboard_employee(client, hr_headers, hire_email)
    employee_access = await login(client, hire_email, password="TempPass123")
    headers = {"Authorization": f"Bearer {employee_access}"}

    # not assigned yet — still rejected
    denied = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert denied.status_code == 400

    assign = await client.post(
        f"/geofences/{geofence_id}/employees/{employee['id']}", headers=hr_headers
    )
    assert assign.status_code == 204

    allowed = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["check_in_geofence_id"] == geofence_id


@pytest.mark.asyncio
async def test_check_out_still_works_after_geofence_deactivated_mid_shift(
    client, db_session, caplog, unique_email
):
    """Deactivating a geofence must stop new check-ins against it, but must
    not strand an employee already checked in there with no self-service way
    to end their shift."""
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    geofence_id = await _create_geofence(client, hr_headers)

    hire_email = f"hire-{unique_email}"
    await _onboard_employee(client, hr_headers, hire_email)
    employee_access = await login(client, hire_email, password="TempPass123")
    headers = {"Authorization": f"Bearer {employee_access}"}

    check_in = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert check_in.status_code == 201, check_in.text

    deactivate = await client.patch(
        f"/geofences/{geofence_id}", json={"is_active": False}, headers=hr_headers
    )
    assert deactivate.status_code == 200

    check_out = await client.post(
        "/attendance/check-out",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert check_out.status_code == 200, check_out.text
    assert check_out.json()["check_out_at"] is not None

    # The deactivated geofence still must not accept a brand new check-in —
    # only the attendance record it already owns gets the exception.
    reject_new_checkin = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert reject_new_checkin.status_code == 400


@pytest.mark.asyncio
async def test_check_in_inside_polygon_geofence_succeeds(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    polygon_points = [
        {"latitude": 36.80, "longitude": 10.18},
        {"latitude": 36.80, "longitude": 10.19},
        {"latitude": 36.81, "longitude": 10.19},
        {"latitude": 36.81, "longitude": 10.18},
    ]
    await client.post(
        "/geofences",
        json={"name": "Chantier", "boundary_type": "polygon", "polygon_points": polygon_points},
        headers=hr_headers,
    )

    hire_email = f"hire-{unique_email}"
    await _onboard_employee(client, hr_headers, hire_email)
    employee_access = await login(client, hire_email, password="TempPass123")
    headers = {"Authorization": f"Bearer {employee_access}"}

    inside = await client.post(
        "/attendance/check-in",
        json={"latitude": 36.805, "longitude": 10.185},
        headers=headers,
    )
    assert inside.status_code == 201, inside.text

    checkout = await client.post(
        "/attendance/check-out",
        json={"latitude": 36.805, "longitude": 10.185},
        headers=headers,
    )
    assert checkout.status_code == 200

    outside = await client.post(
        "/attendance/check-in",
        json={"latitude": FAR_LAT, "longitude": FAR_LNG},
        headers=headers,
    )
    assert outside.status_code == 400


@pytest.mark.asyncio
async def test_check_in_poor_accuracy_rejected(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}

    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 500},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_check_in_mock_location_rejected(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}

    resp = await client.post(
        "/attendance/check-in",
        json={
            "latitude": OFFICE_LAT,
            "longitude": OFFICE_LNG,
            "accuracy_meters": 10,
            "is_mock_location": True,
        },
        headers=headers,
    )
    assert resp.status_code == 400
    assert "mocked/fake location" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_check_in_jailbreak_flagged_not_blocked(client, db_session, caplog, unique_email):
    """Unlike mock-location, a jailbreak signal is weaker (client-side JS
    heuristic, no OS-level guarantee) — it flags the row for HR review, it
    does not refuse the check-in."""
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}

    resp = await client.post(
        "/attendance/check-in",
        json={
            "latitude": OFFICE_LAT,
            "longitude": OFFICE_LNG,
            "accuracy_meters": 10,
            "is_jailbroken": True,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["check_in_is_jailbroken"] is True


@pytest.mark.asyncio
async def test_check_in_defaults_jailbreak_flag_false(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}

    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["check_in_is_jailbroken"] is False


@pytest.mark.asyncio
async def test_check_in_impossible_travel_blocked(client, db_session, caplog, unique_email):
    """Check out at site A, backdate that check-out by 10 minutes (HR
    correction — real wall-clock elapsed time in a test run is milliseconds,
    not enough to exceed the plausible-speed threshold on its own), then
    check in ~22km away at site B. 22km / ~10min implies >120km/h — blocked."""
    employee_access, _, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    site_b_lat = OFFICE_LAT + 0.2  # ~22km north — well beyond any plausible
    # 10-minute ground-travel distance, and well outside FAR_LAT's 1.5km.
    await _create_geofence(
        client, hr_headers, name="Chantier B", center_latitude=site_b_lat, center_longitude=OFFICE_LNG
    )

    check_in_resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert check_in_resp.status_code == 201
    attendance_id = check_in_resp.json()["id"]
    check_out_resp = await client.post(
        "/attendance/check-out",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert check_out_resp.status_code == 200

    backdated = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    correction = await client.patch(
        f"/attendance/{attendance_id}",
        json={"check_out_at": backdated},
        headers=hr_headers,
    )
    assert correction.status_code == 200

    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": site_b_lat, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "physically plausible" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_check_in_impossible_travel_skipped_within_min_elapsed_floor(
    client, db_session, caplog, unique_email
):
    """A real (not backdated) check-out immediately followed by a check-in far
    away has real elapsed time in the millisecond range — below the 5-minute
    floor, so the check is skipped entirely rather than computing an inflated
    speed off a near-zero denominator. This is a deliberate blind spot (see
    PLAN.md T1 edge cases), not a bug: the alternative is false-positive
    blocking on GPS-jitter-scale double-submits."""
    employee_access, _, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    site_b_lat = OFFICE_LAT + 0.2
    await _create_geofence(
        client, hr_headers, name="Chantier B", center_latitude=site_b_lat, center_longitude=OFFICE_LNG
    )

    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    await client.post(
        "/attendance/check-out",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": site_b_lat, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_check_in_ignores_synthetic_last_completed_session_for_impossible_travel(
    client, db_session, caplog, unique_email
):
    """PLAN.md T0 (CRITICAL): a synthetic 'far-away checkout' row must never
    be compared against a real employee's real check-in by the
    impossible-travel gate. Mirrors test_check_in_impossible_travel_blocked's
    exact shape (same 22km/10min setup that DOES block a real prior session)
    but the prior session here is synthetic — proving
    get_last_completed_for_employee's is_synthetic=False filter is load-
    bearing, not decorative."""
    employee_access, employee_id, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    site_b_lat = OFFICE_LAT + 0.2  # ~22km north, same threshold as the real-data test
    await _create_geofence(
        client, hr_headers, name="Chantier B", center_latitude=site_b_lat, center_longitude=OFFICE_LNG
    )

    backdated_checkout = datetime.now(timezone.utc) - timedelta(minutes=10)
    synthetic = Attendance(
        employee_id=uuid.UUID(employee_id),
        attendance_date=backdated_checkout.date(),
        check_in_at=backdated_checkout - timedelta(hours=1),
        check_out_at=backdated_checkout,
        check_out_latitude=OFFICE_LAT,
        check_out_longitude=OFFICE_LNG,
        status=AttendanceStatus.PRESENT,
        is_synthetic=True,
    )
    db_session.add(synthetic)
    await db_session.commit()

    # If the synthetic row above were treated as the "last known position"
    # (site A, 10 minutes ago), this would be blocked exactly like
    # test_check_in_impossible_travel_blocked. It must not be — the employee
    # has no REAL prior session today.
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": site_b_lat, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_double_check_in_rejected(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    body = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}

    first = await client.post("/attendance/check-in", json=body, headers=headers)
    assert first.status_code == 201
    second = await client.post("/attendance/check-in", json=body, headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_check_out_without_check_in_rejected(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    resp = await client.post(
        "/attendance/check-out",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_check_out_happy_path(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    body = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}

    await client.post("/attendance/check-in", json=body, headers=headers)
    resp = await client.post("/attendance/check-out", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["check_out_at"] is not None
    assert resp.json()["check_out_geofence_id"] is not None


@pytest.mark.asyncio
async def test_double_check_out_rejected(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    body = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}

    await client.post("/attendance/check-in", json=body, headers=headers)
    await client.post("/attendance/check-out", json=body, headers=headers)
    second = await client.post("/attendance/check-out", json=body, headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_check_out_with_open_break_rejected(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    body = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}

    await client.post("/attendance/check-in", json=body, headers=headers)
    await client.post("/attendance/break/start", json=body, headers=headers)
    resp = await client.post("/attendance/check-out", json=body, headers=headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_start_break_happy_path_and_double_start_rejected(
    client, db_session, caplog, unique_email
):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )

    on_site = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}
    first = await client.post("/attendance/break/start", json=on_site, headers=headers)
    assert first.status_code == 201
    assert first.json()["break_end_at"] is None
    assert first.json()["start_latitude"] == OFFICE_LAT

    second = await client.post("/attendance/break/start", json=on_site, headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_end_break_happy_path_and_no_active_break_rejected(
    client, db_session, caplog, unique_email
):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    on_site = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}
    await client.post("/attendance/break/start", json=on_site, headers=headers)

    ended = await client.post("/attendance/break/end", json=on_site, headers=headers)
    assert ended.status_code == 200
    assert ended.json()["break_end_at"] is not None
    assert ended.json()["end_latitude"] == OFFICE_LAT

    no_active = await client.post("/attendance/break/end", json=on_site, headers=headers)
    assert no_active.status_code == 409


@pytest.mark.asyncio
async def test_start_break_outside_geofence_rejected(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )

    # Checked in on site, then walked out before starting the break.
    resp = await client.post(
        "/attendance/break/start",
        json={"latitude": FAR_LAT, "longitude": FAR_LNG},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_end_break_outside_geofence_rejected(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    on_site = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}
    await client.post("/attendance/check-in", json=on_site, headers=headers)
    await client.post("/attendance/break/start", json=on_site, headers=headers)

    # Left the zone during the break. Gating both ends was an explicit product
    # decision: the break stays open until the employee is back inside.
    resp = await client.post(
        "/attendance/break/end",
        json={"latitude": FAR_LAT, "longitude": FAR_LNG},
        headers=headers,
    )
    assert resp.status_code == 400

    back_inside = await client.post("/attendance/break/end", json=on_site, headers=headers)
    assert back_inside.status_code == 200


@pytest.mark.asyncio
async def test_break_rejects_poor_gps_accuracy(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )

    resp = await client.post(
        "/attendance/break/start",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 500},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_double_start_break_reports_conflict_not_location(
    client, db_session, caplog, unique_email
):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    on_site = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}
    await client.post("/attendance/check-in", json=on_site, headers=headers)
    await client.post("/attendance/break/start", json=on_site, headers=headers)

    # Already on break AND off site: the conflict must win, so the employee is
    # not sent to fix a location problem that was never the reason for refusal.
    resp = await client.post(
        "/attendance/break/start",
        json={"latitude": FAR_LAT, "longitude": FAR_LNG},
        headers=headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_employee_works_two_chantiers_in_one_day(
    client, db_session, caplog, unique_email
):
    employee_access, _, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    site_a = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}
    # Second chantier, far enough to be its own zone but with its own geofence.
    site_b = {"latitude": FAR_LAT, "longitude": FAR_LNG}
    await _create_geofence(
        client,
        hr_headers,
        name="Chantier B",
        center_latitude=FAR_LAT,
        center_longitude=FAR_LNG,
    )

    assert (await client.post("/attendance/check-in", json=site_a, headers=headers)).status_code == 201
    assert (await client.post("/attendance/check-out", json=site_a, headers=headers)).status_code == 200

    # The whole point: a second check-in the same day, at a different site.
    second = await client.post("/attendance/check-in", json=site_b, headers=headers)
    assert second.status_code == 201, second.text
    assert (await client.post("/attendance/check-out", json=site_b, headers=headers)).status_code == 200

    today = await client.get("/attendance/me/today", headers=headers)
    assert today.json()["current"] is None
    assert len(today.json()["sessions"]) == 2


@pytest.mark.asyncio
async def test_check_in_while_a_session_is_open_rejected(
    client, db_session, caplog, unique_email
):
    employee_access, _, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _create_geofence(
        client,
        hr_headers,
        name="Chantier B",
        center_latitude=FAR_LAT,
        center_longitude=FAR_LNG,
    )

    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    # Still checked in at site A — moving to B without checking out is refused.
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": FAR_LAT, "longitude": FAR_LNG},
        headers=headers,
    )
    assert resp.status_code == 409
    assert "check out" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_can_check_in_again_at_the_same_site(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    site_a = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}

    await client.post("/attendance/check-in", json=site_a, headers=headers)
    await client.post("/attendance/check-out", json=site_a, headers=headers)

    # Coming back to the same site after lunch or a supply run is ordinary work,
    # not an error — the geofence gate already proves they are standing there.
    resp = await client.post("/attendance/check-in", json=site_a, headers=headers)
    assert resp.status_code == 201, resp.text

    today = await client.get("/attendance/me/today", headers=headers)
    assert len(today.json()["sessions"]) == 2


@pytest.mark.asyncio
async def test_check_out_without_an_open_session_rejected(
    client, db_session, caplog, unique_email
):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    site_a = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG}

    await client.post("/attendance/check-in", json=site_a, headers=headers)
    await client.post("/attendance/check-out", json=site_a, headers=headers)

    resp = await client.post("/attendance/check-out", json=site_a, headers=headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_me_today_null_before_check_in_populated_after(
    client, db_session, caplog, unique_email
):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}

    before = await client.get("/attendance/me/today", headers=headers)
    assert before.status_code == 200
    assert before.json()["current"] is None
    assert before.json()["sessions"] == []

    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    after = await client.get("/attendance/me/today", headers=headers)
    assert after.json()["current"] is not None
    assert after.json()["current"]["status"] == "present"
    assert len(after.json()["sessions"]) == 1


@pytest.mark.asyncio
async def test_me_list_only_returns_own_records(client, db_session, caplog, unique_email):
    employee_access, _, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )

    other_email = f"other-{unique_email}"
    other_employee = await _onboard_employee(client, hr_headers, other_email)
    other_access = await login(client, other_email, password="TempPass123")
    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers={"Authorization": f"Bearer {other_access}"},
    )

    mine = await client.get("/attendance/me", headers=headers)
    assert mine.status_code == 200
    assert mine.json()["total"] == 1
    assert mine.json()["items"][0]["employee_id"] != other_employee["id"]


@pytest.mark.asyncio
async def test_employee_cannot_read_all_attendance(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    resp = await client.get(
        "/attendance", headers={"Authorization": f"Bearer {employee_access}"}
    )
    assert resp.status_code == 403


async def _create_department(client, headers, name: str) -> str:
    resp = await client.post("/departments", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_supervisor_can_read_own_department_attendance(
    client, db_session, caplog, unique_email
):
    """attendance:read:all is scoped for a supervisor: they may see records for
    employees in their own department (see GEOFENCING_MVP_REVIEW.md P2 —
    attendance:read:all had no department/ownership scoping)."""
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    dept_id = await _create_department(client, hr_headers, f"Dept-{unique_email}")
    await _create_geofence(client, hr_headers)  # global geofence, no department_id

    hire_email = f"hire-{unique_email}"
    employee = await _onboard_employee(client, hr_headers, hire_email, department_id=dept_id)
    employee_access = await login(client, hire_email, password="TempPass123")
    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers={"Authorization": f"Bearer {employee_access}"},
    )

    supervisor_email = f"supervisor-{unique_email}"
    await _onboard_employee(
        client,
        hr_headers,
        supervisor_email,
        role_name="supervisor",
        department_id=dept_id,
    )
    supervisor_access = await login(client, supervisor_email, password="TempPass123")

    resp = await client.get(
        f"/attendance?employee_id={employee['id']}",
        headers={"Authorization": f"Bearer {supervisor_access}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    single = await client.get(
        f"/attendance/{resp.json()['items'][0]['id']}",
        headers={"Authorization": f"Bearer {supervisor_access}"},
    )
    assert single.status_code == 200


@pytest.mark.asyncio
async def test_supervisor_cannot_read_other_department_attendance(
    client, db_session, caplog, unique_email
):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    own_dept_id = await _create_department(client, hr_headers, f"Own-{unique_email}")
    other_dept_id = await _create_department(client, hr_headers, f"Other-{unique_email}")
    await _create_geofence(client, hr_headers)

    hire_email = f"hire-{unique_email}"
    employee = await _onboard_employee(
        client, hr_headers, hire_email, department_id=other_dept_id
    )
    employee_access = await login(client, hire_email, password="TempPass123")
    checkin = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    attendance_id = checkin.json()["id"]

    supervisor_email = f"supervisor-{unique_email}"
    await _onboard_employee(
        client,
        hr_headers,
        supervisor_email,
        role_name="supervisor",
        department_id=own_dept_id,
    )
    supervisor_access = await login(client, supervisor_email, password="TempPass123")
    supervisor_headers = {"Authorization": f"Bearer {supervisor_access}"}

    scoped_out = await client.get(
        f"/attendance?department_id={other_dept_id}", headers=supervisor_headers
    )
    assert scoped_out.status_code == 403

    listed = await client.get(
        f"/attendance?employee_id={employee['id']}", headers=supervisor_headers
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 0

    single = await client.get(f"/attendance/{attendance_id}", headers=supervisor_headers)
    assert single.status_code == 404


@pytest.mark.asyncio
async def test_admin_read_all_attendance_not_department_scoped(
    client, db_session, caplog, unique_email
):
    """Unlike supervisor, roles above it (admin/hr_manager/auditor/super_admin)
    are not department-scoped — they legitimately need company-wide visibility."""
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    dept_id = await _create_department(client, hr_headers, f"Dept-{unique_email}")
    await _create_geofence(client, hr_headers)

    hire_email = f"hire-{unique_email}"
    employee = await _onboard_employee(client, hr_headers, hire_email, department_id=dept_id)
    employee_access = await login(client, hire_email, password="TempPass123")
    await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers={"Authorization": f"Bearer {employee_access}"},
    )

    admin_access = await _make_admin(client, db_session, caplog, f"admin-{unique_email}")
    resp = await client.get(
        f"/attendance?employee_id={employee['id']}",
        headers={"Authorization": f"Bearer {admin_access}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_manual_entry_creation_by_supervisor(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    hire_email = f"hire-{unique_email}"
    employee = await _onboard_employee(client, hr_headers, hire_email)

    resp = await client.post(
        f"/attendance/{employee['id']}/manual-entry",
        json={
            "attendance_date": "2026-02-01",
            "check_in_at": "2026-02-01T09:00:00Z",
            "check_out_at": "2026-02-01T17:00:00Z",
            "status": "remote",
            "notes": "Backfilled by HR",
        },
        headers=hr_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["is_manual_entry"] is True
    assert body["status"] == "remote"
    assert body["check_in_latitude"] is None


@pytest.mark.asyncio
async def test_manual_entry_on_existing_day_rejected(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    hire_email = f"hire-{unique_email}"
    employee = await _onboard_employee(client, hr_headers, hire_email)

    payload = {
        "attendance_date": "2026-02-01",
        "check_in_at": "2026-02-01T09:00:00Z",
        "status": "present",
    }
    first = await client.post(
        f"/attendance/{employee['id']}/manual-entry", json=payload, headers=hr_headers
    )
    assert first.status_code == 201
    second = await client.post(
        f"/attendance/{employee['id']}/manual-entry", json=payload, headers=hr_headers
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_correction_updates_fields_and_requires_permission(
    client, db_session, caplog, unique_email
):
    employee_access, _, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    checked_in = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    attendance_id = checked_in.json()["id"]

    forbidden = await client.patch(
        f"/attendance/{attendance_id}",
        json={"status": "late"},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert forbidden.status_code == 403

    corrected = await client.patch(
        f"/attendance/{attendance_id}",
        json={"status": "late", "notes": "Corrected by HR"},
        headers=hr_headers,
    )
    assert corrected.status_code == 200
    assert corrected.json()["status"] == "late"
    assert corrected.json()["notes"] == "Corrected by HR"


@pytest.mark.asyncio
async def test_get_unknown_attendance_404(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    resp = await client.get(
        f"/attendance/{uuid.uuid4()}", headers={"Authorization": f"Bearer {hr_access}"}
    )
    assert resp.status_code == 404


# --- Face-gated check-in -----------------------------------------------------
# Pipeline mocked exactly like test_face_recognition.py (no real photos in CI).
# These tests explicitly flip FACE_VERIFICATION_ENABLED on per-test — the
# global default is False, so every test above this section is completely
# unaffected by this module existing.


def _face_embedding(seed: float, dim: int = 4) -> list:
    raw = [seed + i for i in range(dim)]
    norm = sum(v * v for v in raw) ** 0.5
    return [v / norm for v in raw]


def _b64_photo() -> str:
    return base64.b64encode(b"\xff\xd8\xff\xe0not a real jpeg").decode()


@pytest.fixture
def _enable_face_verification(monkeypatch):
    from app.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "face_verification_enabled", True)


async def _enroll(client, hr_headers, employee_id, monkeypatch, embedding):
    from app.services import face_service

    monkeypatch.setattr(
        face_service.face_pipeline, "analyze", lambda image_bytes: SimpleNamespace(embedding=embedding, liveness=0.9)
    )
    resp = await client.post(
        f"/face/enroll/{employee_id}",
        files=[("photos", ("a.jpg", b"fake", "image/jpeg"))],
        headers=hr_headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_check_in_face_match_succeeds(
    client, db_session, caplog, unique_email, monkeypatch, _enable_face_verification
):
    employee_access, employee_id, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    embedding = _face_embedding(1.0)
    await _enroll(client, hr_headers, employee_id, monkeypatch, embedding)

    from app.services import face_service

    monkeypatch.setattr(
        face_service.face_pipeline, "analyze", lambda image_bytes: SimpleNamespace(embedding=embedding, liveness=0.9)
    )
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "selfie_base64": _b64_photo()},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_check_in_face_mismatch_rejected_and_no_row_created(
    client, db_session, caplog, unique_email, monkeypatch, _enable_face_verification
):
    employee_access, employee_id, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    await _enroll(client, hr_headers, employee_id, monkeypatch, _face_embedding(1.0))

    from app.services import face_service

    monkeypatch.setattr(
        face_service.face_pipeline,
        "analyze",
        lambda image_bytes: SimpleNamespace(embedding=[0.0, 1.0, 0.0, 0.0], liveness=0.9),
    )
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "selfie_base64": _b64_photo()},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 400, resp.text

    # No attendance row was created by the rejected attempt — confirmed by a
    # subsequent successful check-in not hitting AlreadyCheckedInError.
    monkeypatch.setattr(
        face_service.face_pipeline,
        "analyze",
        lambda image_bytes: SimpleNamespace(embedding=_face_embedding(1.0), liveness=0.9),
    )
    retry = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "selfie_base64": _b64_photo()},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert retry.status_code == 201, retry.text


@pytest.mark.asyncio
async def test_check_in_liveness_failure_rejected(
    client, db_session, caplog, unique_email, monkeypatch, _enable_face_verification
):
    employee_access, employee_id, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    embedding = _face_embedding(1.0)
    await _enroll(client, hr_headers, employee_id, monkeypatch, embedding)

    from app.services import face_service

    monkeypatch.setattr(
        face_service.face_pipeline,
        "analyze",
        lambda image_bytes: SimpleNamespace(embedding=embedding, liveness=0.0),
    )
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "selfie_base64": _b64_photo()},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_check_in_unenrolled_employee_blocked(
    client, db_session, caplog, unique_email, _enable_face_verification
):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "selfie_base64": _b64_photo()},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_check_in_missing_selfie_rejected_when_enabled(
    client, db_session, caplog, unique_email, monkeypatch, _enable_face_verification
):
    employee_access, employee_id, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    await _enroll(client, hr_headers, employee_id, monkeypatch, _face_embedding(1.0))

    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_check_in_ignores_unenrolled_employee_when_flag_off(
    client, db_session, caplog, unique_email
):
    """Regression guard: with the default (flag off), check-in must behave
    exactly as it did before this module existed, selfie or not."""
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers={"Authorization": f"Bearer {employee_access}"},
    )
    assert resp.status_code == 201, resp.text
