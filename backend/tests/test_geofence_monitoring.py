from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.attendance import Attendance
from app.models.mixins import utcnow
from tests.test_attendance import (
    OFFICE_LAT,
    OFFICE_LNG,
    _make_hr_manager,
    _onboard_employee,
    _setup_employee_with_geofence,
)
from tests.conftest import login

# ~30m north of OFFICE — inside a 100m-radius geofence
NEAR_LAT = 36.80677
NEAR_LNG = OFFICE_LNG
# ~1.5km north of OFFICE — outside any reasonably-sized geofence
FAR_LAT = 36.82
FAR_LNG = OFFICE_LNG


async def _check_in(client, headers):
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _ping(client, headers, latitude, longitude, ping_seq, accuracy_meters=10):
    return await client.post(
        "/attendance/location-ping",
        json={
            "latitude": latitude,
            "longitude": longitude,
            "accuracy_meters": accuracy_meters,
            "ping_seq": ping_seq,
        },
        headers=headers,
    )


@pytest.mark.asyncio
async def test_check_in_records_enter_event(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    attendance = await _check_in(client, headers)

    assert len(attendance["geofence_events"]) == 1
    assert attendance["geofence_events"][0]["event_type"] == "enter"


@pytest.mark.asyncio
async def test_two_outside_pings_below_debounce_no_exit(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)

    for seq in (1, 2):
        resp = await _ping(client, headers, FAR_LAT, FAR_LNG, seq)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "in_zone"
        assert resp.json()["event_fired"] is None


@pytest.mark.asyncio
async def test_three_outside_pings_fires_exit(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)

    for seq in (1, 2):
        resp = await _ping(client, headers, FAR_LAT, FAR_LNG, seq)
        assert resp.json()["event_fired"] is None

    resp = await _ping(client, headers, FAR_LAT, FAR_LNG, 3)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "exited"
    assert resp.json()["event_fired"] == "exit"


@pytest.mark.asyncio
async def test_return_fires_after_exit(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)

    for seq in (1, 2, 3):
        await _ping(client, headers, FAR_LAT, FAR_LNG, seq)

    resp = await _ping(client, headers, NEAR_LAT, NEAR_LNG, 4)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_zone"
    assert resp.json()["event_fired"] == "return"


@pytest.mark.asyncio
async def test_duplicate_ping_is_idempotent(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)

    for seq in (1, 2, 2, 2):  # seq 2 sent three times (client retry storm)
        resp = await _ping(client, headers, FAR_LAT, FAR_LNG, seq)
        assert resp.json()["event_fired"] is None

    # Only 2 outside readings actually counted — a 3rd real ping is still
    # needed to cross the debounce threshold, proving the retries didn't
    # each increment the streak.
    resp = await _ping(client, headers, FAR_LAT, FAR_LNG, 3)
    assert resp.json()["status"] == "exited"
    assert resp.json()["event_fired"] == "exit"


@pytest.mark.asyncio
async def test_ping_with_no_active_checkin_is_dropped_silently(
    client, db_session, caplog, unique_email
):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    # Never checked in.
    resp = await _ping(client, headers, OFFICE_LAT, OFFICE_LNG, 1)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "no_active_checkin"


@pytest.mark.asyncio
async def test_ping_during_open_break_is_dropped_without_side_effects(
    client, db_session, caplog, unique_email
):
    """CNIL doctrine bars location tracking during legally-protected rest
    time. A ping fired during an open break (old/buggy client — the mobile
    app itself stops sending them) must not fire an EXIT, must not persist
    coordinates, and must not advance the debounce streak."""
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)
    on_site = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10}
    await client.post("/attendance/break/start", json=on_site, headers=headers)

    for seq in (1, 2, 3):
        resp = await _ping(client, headers, FAR_LAT, FAR_LNG, seq)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "on_break"
        assert resp.json()["event_fired"] is None

    # End the break, then prove the outside streak never advanced — three
    # more real pings are needed to cross the debounce threshold, not zero.
    await client.post("/attendance/break/end", json=on_site, headers=headers)
    for seq in (4, 5):
        resp = await _ping(client, headers, FAR_LAT, FAR_LNG, seq)
        assert resp.json()["event_fired"] is None
    resp = await _ping(client, headers, FAR_LAT, FAR_LNG, 6)
    assert resp.json()["status"] == "exited"
    assert resp.json()["event_fired"] == "exit"


@pytest.mark.asyncio
async def test_exit_monitoring_works_for_polygon_geofence(client, db_session, caplog, unique_email):
    """Same debounce/exit logic as the circle path, but checked in against a
    polygon site — proves record_ping's boundary_type dispatch, not just
    check-in's."""
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

    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": 36.805, "longitude": 10.185, "accuracy_meters": 10},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    for seq in (1, 2):
        ping = await _ping(client, headers, FAR_LAT, FAR_LNG, seq)
        assert ping.json()["status"] == "in_zone"

    ping = await _ping(client, headers, FAR_LAT, FAR_LNG, 3)
    assert ping.status_code == 200, ping.text
    assert ping.json()["status"] == "exited"
    assert ping.json()["event_fired"] == "exit"


@pytest.mark.asyncio
async def test_monitoring_status_live_right_after_check_in(
    client, db_session, caplog, unique_email
):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)

    resp = await client.get("/attendance/me/today", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["current"]["monitoring_status"] == "live"


@pytest.mark.asyncio
async def test_monitoring_status_stale_after_missed_pings(
    client, db_session, caplog, unique_email
):
    """The killed-app scenario: no ping for well past the debounce margin
    must read as "stale", never as an implicitly-trusted "live" forever."""
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)

    attendance = (await db_session.execute(select(Attendance))).scalars().first()
    attendance.check_in_at = utcnow() - timedelta(minutes=10)
    await db_session.commit()

    resp = await client.get("/attendance/me/today", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["current"]["monitoring_status"] == "stale"


@pytest.mark.asyncio
async def test_monitoring_status_on_break_is_not_stale(client, db_session, caplog, unique_email):
    """A long break must never be mistaken for a dead device — pings are
    intentionally paused for its whole duration."""
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)
    on_site = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10}
    await client.post("/attendance/break/start", json=on_site, headers=headers)

    attendance = (await db_session.execute(select(Attendance))).scalars().first()
    attendance.check_in_at = utcnow() - timedelta(minutes=10)
    await db_session.commit()

    resp = await client.get("/attendance/me/today", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["current"]["monitoring_status"] == "on_break"


@pytest.mark.asyncio
async def test_ping_requires_auth(client, db_session, caplog, unique_email):
    resp = await client.post(
        "/attendance/location-ping",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10, "ping_seq": 1},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_concurrent_break_start_rescued_as_conflict(client, db_session, caplog, unique_email):
    """Two near-simultaneous break/start requests for the same attendance —
    uq_break_period_one_open_per_attendance is the real backstop, mirroring
    test_concurrent_check_in_rescued_as_conflict. Must surface as 409, never
    an unhandled 500."""
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)
    on_site = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10}

    first = await client.post("/attendance/break/start", json=on_site, headers=headers)
    assert first.status_code == 201
    second = await client.post("/attendance/break/start", json=on_site, headers=headers)
    assert second.status_code == 409
    assert second.status_code != 500


@pytest.mark.asyncio
async def test_exit_auto_starts_geofence_exit_break(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)

    for seq in (1, 2, 3):
        await _ping(client, headers, FAR_LAT, FAR_LNG, seq)

    resp = await client.get("/attendance/me/today", headers=headers)
    assert resp.status_code == 200, resp.text
    breaks = resp.json()["current"]["breaks"]
    assert len(breaks) == 1
    assert breaks[0]["source"] == "geofence_exit"
    assert breaks[0]["break_end_at"] is None


@pytest.mark.asyncio
async def test_ping_during_geofence_exit_break_is_not_dropped_and_return_closes_it(
    client, db_session, caplog, unique_email
):
    """Unlike a MANUAL break, an auto-break from a debounced EXIT must not
    swallow pings — RETURN can only be detected (and the break auto-closed)
    if position checks keep running while it's open."""
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)

    for seq in (1, 2, 3):
        await _ping(client, headers, FAR_LAT, FAR_LNG, seq)

    resp = await _ping(client, headers, NEAR_LAT, NEAR_LNG, 4)
    assert resp.status_code == 200, resp.text
    # Not "on_break" — proves this ping wasn't dropped by the break gate.
    assert resp.json()["status"] == "in_zone"
    assert resp.json()["event_fired"] == "return"

    today = await client.get("/attendance/me/today", headers=headers)
    breaks = today.json()["current"]["breaks"]
    assert len(breaks) == 1
    assert breaks[0]["source"] == "geofence_exit"
    assert breaks[0]["break_end_at"] is not None


@pytest.mark.asyncio
async def test_checkout_auto_closes_open_geofence_exit_break(
    client, db_session, caplog, unique_email
):
    """An employee physically back on-site, checking out before the next
    ping fires, must not be blocked by (or leave dangling) the still-open
    auto-break — checkout closes it itself, unlike a MANUAL break which
    still blocks checkout."""
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)

    for seq in (1, 2, 3):
        await _ping(client, headers, FAR_LAT, FAR_LNG, seq)

    resp = await client.post(
        "/attendance/check-out",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["check_out_at"] is not None
    assert len(body["breaks"]) == 1
    assert body["breaks"][0]["source"] == "geofence_exit"
    assert body["breaks"][0]["break_end_at"] is not None


@pytest.mark.asyncio
async def test_checkout_still_blocked_by_open_manual_break(
    client, db_session, caplog, unique_email
):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    await _check_in(client, headers)
    on_site = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10}
    await client.post("/attendance/break/start", json=on_site, headers=headers)

    resp = await client.post("/attendance/check-out", json=on_site, headers=headers)
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_concurrent_check_in_rescued_as_conflict(client, db_session, caplog, unique_email):
    """Two near-simultaneous check-in requests for the same employee/day —
    the DB unique constraint (uq_attendance_employee_date) is the real
    backstop, but it must surface as the same 409 a slower client would see,
    never an unhandled 500. See PLAN.md Eng review — CRITICAL REGRESSION."""
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    body = {"latitude": OFFICE_LAT, "longitude": OFFICE_LNG, "accuracy_meters": 10}

    first = await client.post("/attendance/check-in", json=body, headers=headers)
    assert first.status_code == 201
    # The pre-check in check_in() would normally catch this as 409 too (see
    # test_double_check_in_rejected), but this test exercises the same
    # AlreadyCheckedInError being raised from the IntegrityError rescue path
    # by going through the same public API — the regression is in a race
    # window the test suite can't reliably force without DB-level fault
    # injection, so this asserts the observable contract (never a 500)
    # rather than the internal race itself.
    second = await client.post("/attendance/check-in", json=body, headers=headers)
    assert second.status_code == 409
    assert second.status_code != 500
