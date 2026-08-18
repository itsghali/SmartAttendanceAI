"""PLAN.md Module 3 / Candidate 6: the impossible-travel gate
(attendance_service._check_impossible_travel_or_raise) has always been a
hard, unmodified check-in-blocking rule -- these tests only cover the NEW
audit trail it now writes on rejection, not the gate itself (see
test_attendance.py's own test_check_in_impossible_travel_blocked for that).

The one property that matters most here: the audit row must survive even
though the rejected request's own transaction gets rolled back by get_db(),
and an audit-write failure must never weaken the rejection itself.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.impossible_travel_rejection import ImpossibleTravelRejection
from tests.test_attendance import (
    OFFICE_LAT,
    OFFICE_LNG,
    _create_geofence,
    _setup_employee_with_geofence,
)


async def _trigger_rejection(client, db_session, caplog, unique_email):
    """Same setup as test_attendance.test_check_in_impossible_travel_blocked
    -- check out at site A, backdate the check-out by 10 minutes, then check
    in ~22km away at site B."""
    employee_access, _, hr_headers = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    site_b_lat = OFFICE_LAT + 0.2
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
    return resp, headers, hr_headers, attendance_id


@pytest.mark.asyncio
async def test_rejection_persists_audit_row_surviving_the_request_rollback(
    client, db_session, caplog, unique_email
):
    resp, headers, hr_headers, prior_attendance_id = await _trigger_rejection(
        client, db_session, caplog, unique_email
    )
    assert resp.status_code == 400
    # get_db() rolled back the request's own session on the raised
    # exception -- if the audit row weren't independently committed inside
    # _check_impossible_travel_or_raise, it would have vanished along with
    # everything else in that transaction. Re-fetch on a fresh query to
    # prove it's actually durable, not just present in an identity map.
    row = (
        (await db_session.execute(select(ImpossibleTravelRejection))).scalars().one()
    )
    assert str(row.prior_attendance_id) == prior_attendance_id
    assert row.distance_km == pytest.approx(22.24, abs=0.5)
    assert row.elapsed_hours == pytest.approx(1 / 6, abs=0.01)  # 10 minutes
    assert row.implied_speed_kmh > 120.0
    assert row.risk_score > 0.0


@pytest.mark.asyncio
async def test_non_rejected_check_in_writes_no_audit_row(client, db_session, caplog, unique_email):
    employee_access, _, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    resp = await client.post(
        "/attendance/check-in",
        json={"latitude": OFFICE_LAT, "longitude": OFFICE_LNG},
        headers=headers,
    )
    assert resp.status_code == 201
    rows = (await db_session.execute(select(ImpossibleTravelRejection))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_audit_write_failure_does_not_weaken_the_rejection(
    client, db_session, caplog, unique_email, monkeypatch
):
    """Even if persisting the audit row itself fails, the check-in must
    still be blocked -- the audit trail is evidence for later review, never
    a precondition for the security gate holding."""
    from app.repositories.impossible_travel_rejection_repository import (
        ImpossibleTravelRejectionRepository,
    )

    async def _boom(self, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(ImpossibleTravelRejectionRepository, "create", _boom)

    resp, *_ = await _trigger_rejection(client, db_session, caplog, unique_email)
    assert resp.status_code == 400
    assert "physically plausible" in resp.json()["detail"]
    rows = (await db_session.execute(select(ImpossibleTravelRejection))).scalars().all()
    assert rows == []  # the write failed, as simulated -- confirms it was actually attempted


@pytest.mark.asyncio
async def test_list_rejections_route_and_permission_gating(client, db_session, caplog, unique_email):
    resp, headers, hr_headers, _ = await _trigger_rejection(client, db_session, caplog, unique_email)
    assert resp.status_code == 400

    list_resp = await client.get(
        "/workforce-intelligence/impossible-travel-rejections", headers=hr_headers
    )
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] == 1
    assert body["items"][0]["risk_score"] > 0.0

    employee_forbidden = await client.get(
        "/workforce-intelligence/impossible-travel-rejections", headers=headers
    )
    assert employee_forbidden.status_code == 403
