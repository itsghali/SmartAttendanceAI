"""GOVERNANCE.md Section 3: 12-month retention, enforced by
backend/scripts/purge_expired_workforce_intelligence_audit_records.py.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.attendance import Attendance
from app.models.employee_deviation_flag import DeviationSeverity, EmployeeDeviationFlag
from app.models.face_verification_attempt import FaceVerificationAttempt
from app.models.geofence_event import GeofenceEvent, GeofenceEventType
from app.models.impossible_travel_rejection import ImpossibleTravelRejection
from app.models.mixins import utcnow
from scripts.purge_expired_workforce_intelligence_audit_records import RETENTION, purge
from tests.test_workforce_intelligence_baseline import _employee_role_id, _make_bare_employee


@pytest.mark.asyncio
async def test_purge_deletes_only_rows_older_than_retention_window(
    client, db_session, caplog, unique_email
):
    role_id = await _employee_role_id(db_session)
    hashed = hash_password("unused")
    employee = await _make_bare_employee(db_session, role_id, hashed)

    attendance = Attendance(
        employee_id=employee.id,
        attendance_date=date(2026, 1, 5),
        check_in_at=utcnow(),
    )
    db_session.add(attendance)
    await db_session.flush()

    now = utcnow()
    old = now - RETENTION - timedelta(days=1)
    recent = now - timedelta(days=1)

    old_event = GeofenceEvent(
        employee_id=employee.id,
        attendance_id=attendance.id,
        event_type=GeofenceEventType.ENTER,
        latitude=0.0,
        longitude=0.0,
        created_at=old,
    )
    recent_event = GeofenceEvent(
        employee_id=employee.id,
        attendance_id=attendance.id,
        event_type=GeofenceEventType.ENTER,
        latitude=0.0,
        longitude=0.0,
        created_at=recent,
    )
    old_attempt = FaceVerificationAttempt(
        employee_id=employee.id, passed=True, created_at=old
    )
    recent_attempt = FaceVerificationAttempt(
        employee_id=employee.id, passed=True, created_at=recent
    )
    old_rejection = ImpossibleTravelRejection(
        employee_id=employee.id,
        prior_attendance_id=attendance.id,
        attempted_at=old,
        distance_km=50.0,
        elapsed_hours=0.5,
        implied_speed_kmh=100.0,
        risk_score=1.0,
        created_at=old,
    )
    recent_rejection = ImpossibleTravelRejection(
        employee_id=employee.id,
        prior_attendance_id=attendance.id,
        attempted_at=recent,
        distance_km=50.0,
        elapsed_hours=0.5,
        implied_speed_kmh=100.0,
        risk_score=1.0,
        created_at=recent,
    )
    old_flag = EmployeeDeviationFlag(
        employee_id=employee.id,
        attendance_id=attendance.id,
        metric="checkin_time_of_day_minutes",
        occurred_at=old,
        observed_value=500.0,
        self_mean=400.0,
        self_std=10.0,
        self_z=10.0,
        peer_mean=400.0,
        peer_std=10.0,
        peer_z=10.0,
        severity=DeviationSeverity.HIGH,
        window_start=date(2026, 1, 1),
        window_end=date(2026, 1, 31),
        detected_at=old,
        created_at=old,
    )
    recent_flag = EmployeeDeviationFlag(
        employee_id=employee.id,
        attendance_id=attendance.id,
        metric="checkin_time_of_day_minutes",
        occurred_at=recent,
        observed_value=500.0,
        self_mean=400.0,
        self_std=10.0,
        self_z=10.0,
        peer_mean=400.0,
        peer_std=10.0,
        peer_z=10.0,
        severity=DeviationSeverity.HIGH,
        window_start=date(2026, 1, 1),
        window_end=date(2026, 1, 31),
        detected_at=recent,
        created_at=recent,
    )
    db_session.add_all(
        [
            old_event,
            recent_event,
            old_attempt,
            recent_attempt,
            old_rejection,
            recent_rejection,
            old_flag,
            recent_flag,
        ]
    )
    await db_session.flush()

    cutoff = now - RETENTION
    results = await purge(db_session, cutoff)

    assert results == {
        "geofence_events": 1,
        "face_verification_attempts": 1,
        "impossible_travel_rejections": 1,
        "employee_deviation_flags": 1,
    }

    remaining_events = (await db_session.execute(select(GeofenceEvent))).scalars().all()
    assert [e.id for e in remaining_events] == [recent_event.id]

    remaining_attempts = (
        (await db_session.execute(select(FaceVerificationAttempt))).scalars().all()
    )
    assert [a.id for a in remaining_attempts] == [recent_attempt.id]

    remaining_rejections = (
        (await db_session.execute(select(ImpossibleTravelRejection))).scalars().all()
    )
    assert [r.id for r in remaining_rejections] == [recent_rejection.id]

    remaining_flags = (
        (await db_session.execute(select(EmployeeDeviationFlag))).scalars().all()
    )
    assert [f.id for f in remaining_flags] == [recent_flag.id]


@pytest.mark.asyncio
async def test_purge_is_a_noop_when_nothing_is_old_enough(client, db_session, caplog, unique_email):
    cutoff = utcnow() - RETENTION
    results = await purge(db_session, cutoff)
    assert all(count == 0 for count in results.values())
