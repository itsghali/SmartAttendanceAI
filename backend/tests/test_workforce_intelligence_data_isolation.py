"""PLAN.md T1: every existing read path touching Attendance/BreakPeriod/
GeofenceEvent must filter is_synthetic=false by default, so a Workforce
Intelligence synthetic-data batch (not yet built — that's Sprint 3/T2/T9)
never silently shows up in an HR-facing view or a real employee's own data.

These tests insert synthetic rows directly via the ORM (db_session.add), not
through a generator endpoint, since Module 1's generator doesn't exist yet at
this sprint — the point here is proving the repository-layer filter itself,
independent of whatever eventually writes synthetic rows.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.attendance import Attendance, AttendanceStatus
from app.models.break_period import BreakPeriod
from app.models.geofence_event import GeofenceEvent, GeofenceEventType
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.break_period_repository import BreakPeriodRepository
from app.repositories.geofence_event_repository import GeofenceEventRepository
from tests.test_attendance import _setup_employee_with_geofence

logging.getLogger("app.email").setLevel(logging.INFO)


@pytest.mark.asyncio
async def test_attendance_repository_excludes_synthetic_rows(
    client, db_session, caplog, unique_email
):
    employee_access, employee_id, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}

    check_in = await client.post(
        "/attendance/check-in",
        json={"latitude": 36.8065, "longitude": 10.1815, "accuracy_meters": 10},
        headers=headers,
    )
    assert check_in.status_code == 201
    real_id = check_in.json()["id"]
    check_out = await client.post(
        "/attendance/check-out",
        json={"latitude": 36.8065, "longitude": 10.1815},
        headers=headers,
    )
    assert check_out.status_code == 200

    now = datetime.now(timezone.utc)
    synthetic_closed = Attendance(
        employee_id=uuid.UUID(employee_id),
        attendance_date=now.date(),
        check_in_at=now - timedelta(hours=2),
        check_out_at=now - timedelta(hours=1),
        status=AttendanceStatus.PRESENT,
        is_synthetic=True,
    )
    synthetic_open = Attendance(
        employee_id=uuid.UUID(employee_id),
        attendance_date=now.date(),
        check_in_at=now,
        status=AttendanceStatus.PRESENT,
        is_synthetic=True,
    )
    db_session.add_all([synthetic_closed, synthetic_open])
    await db_session.commit()

    repo = AttendanceRepository(db_session)

    last_completed = await repo.get_last_completed_for_employee(uuid.UUID(employee_id))
    assert last_completed is not None
    assert str(last_completed.id) == real_id, "must return the REAL session, not the synthetic one"

    all_for_employee = await repo.list_all_for_employee(uuid.UUID(employee_id), None, None)
    assert {str(a.id) for a in all_for_employee} == {real_id}

    open_company_wide = await repo.list_open()
    assert synthetic_open.id not in {a.id for a in open_company_wide}

    paginated, total = await repo.list_paginated(
        employee_id=uuid.UUID(employee_id),
        department_id=None,
        date_from=None,
        date_to=None,
        limit=50,
        offset=0,
    )
    assert {str(a.id) for a in paginated} == {real_id}
    assert total == 1


@pytest.mark.asyncio
async def test_break_period_repository_excludes_synthetic_open_break(
    client, db_session, caplog, unique_email
):
    employee_access, employee_id, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    check_in = await client.post(
        "/attendance/check-in",
        json={"latitude": 36.8065, "longitude": 10.1815},
        headers=headers,
    )
    attendance_id = uuid.UUID(check_in.json()["id"])

    synthetic_break = BreakPeriod(
        attendance_id=attendance_id,
        break_start_at=datetime.now(timezone.utc),
        is_synthetic=True,
    )
    db_session.add(synthetic_break)
    await db_session.commit()

    open_break = await BreakPeriodRepository(db_session).get_open_for_attendance(attendance_id)
    assert open_break is None, "a synthetic phantom break must not read as a real open break"


@pytest.mark.asyncio
async def test_geofence_event_repository_excludes_synthetic_events(
    client, db_session, caplog, unique_email
):
    employee_access, employee_id, _ = await _setup_employee_with_geofence(
        client, db_session, caplog, unique_email
    )
    headers = {"Authorization": f"Bearer {employee_access}"}
    check_in = await client.post(
        "/attendance/check-in",
        json={"latitude": 36.8065, "longitude": 10.1815},
        headers=headers,
    )
    attendance_id = uuid.UUID(check_in.json()["id"])

    real_event = await GeofenceEventRepository(db_session).create(
        employee_id=uuid.UUID(employee_id),
        attendance_id=attendance_id,
        geofence_id=None,
        event_type=GeofenceEventType.ENTER,
        latitude=36.8065,
        longitude=10.1815,
    )

    later_synthetic = GeofenceEvent(
        employee_id=uuid.UUID(employee_id),
        attendance_id=attendance_id,
        event_type=GeofenceEventType.EXIT,
        latitude=36.82,
        longitude=10.1815,
        is_synthetic=True,
    )
    db_session.add(later_synthetic)
    await db_session.commit()

    repo = GeofenceEventRepository(db_session)
    latest = await repo.get_latest_for_attendance(attendance_id)
    assert latest is not None
    assert latest.id == real_event.id, "must return the REAL event, not the later synthetic one"

    # check-in itself auto-records a real ENTER event, so real_event (also
    # ENTER, created explicitly above) is one of possibly several real rows —
    # the point under test is that the synthetic EXIT never appears, not an
    # exact count of real ones.
    all_event_ids = {e.id for e in await repo.list_all_for_employee(
        uuid.UUID(employee_id), None, None, None
    )}
    assert real_event.id in all_event_ids
    assert later_synthetic.id not in all_event_ids
