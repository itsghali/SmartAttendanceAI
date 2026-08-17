"""PLAN.md Sprint 3 (Module 1 - synthetic data generator): live-verifies
T2 (single-transaction generation, full rollback + FAILED status on any
mid-batch exception), T9 (per-row anomaly labels persist through the ORM
round-trip), T12 (3-table referential consistency survives bulk-insert), and
T13 (a synthetic "forgot to check out" row never collides with a real open
session).

T0/T1 (is_synthetic read-path filtering) already have their own coverage in
test_workforce_intelligence_data_isolation.py - not repeated here.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.models.attendance import Attendance
from app.models.break_period import BreakPeriod
from app.models.geofence_event import GeofenceEvent
from app.models.synthetic_data_run import SyntheticDataRun, SyntheticDataRunStatus
from app.repositories.geofence_event_repository import GeofenceEventRepository
from app.services.workforce_intelligence_service import (
    SyntheticGenerationError,
    WorkforceIntelligenceService,
)
from tests.test_attendance import _make_hr_manager, _onboard_employee, _setup_employee_with_geofence
from workforce_intelligence.exceptions import SyntheticConfigError


@pytest.mark.asyncio
async def test_generate_creates_referentially_consistent_tagged_rows(
    client, db_session, caplog, unique_email
):
    _, employee_id, _ = await _setup_employee_with_geofence(client, db_session, caplog, unique_email)
    service = WorkforceIntelligenceService(db_session)

    run = await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[uuid.UUID(employee_id)],
        date_range_start=date(2026, 2, 2),
        date_range_end=date(2026, 2, 13),
        anomaly_config={"late_arrival": 0.2, "long_break": 0.2, "far_checkout": 0.2},
        seed=42,
    )

    assert run.status == SyntheticDataRunStatus.COMPLETED
    assert run.row_counts["attendance"] == 10  # 2 work weeks, Mon-Fri

    attendance_rows = (
        await db_session.execute(
            select(Attendance).where(Attendance.synthetic_run_id == run.id)
        )
    ).scalars().all()
    assert len(attendance_rows) == 10
    assert all(a.is_synthetic for a in attendance_rows)
    assert all(a.employee_id == uuid.UUID(employee_id) for a in attendance_rows)
    assert all(a.check_out_at is None or a.check_in_at < a.check_out_at for a in attendance_rows)

    break_rows = (
        await db_session.execute(select(BreakPeriod).where(BreakPeriod.synthetic_run_id == run.id))
    ).scalars().all()
    for b in break_rows:
        assert b.is_synthetic
        attendance = next(a for a in attendance_rows if a.id == b.attendance_id)
        assert attendance.check_in_at <= b.break_start_at < b.break_end_at
        if attendance.check_out_at is not None:
            assert b.break_end_at <= attendance.check_out_at

    event_rows = (
        await db_session.execute(select(GeofenceEvent).where(GeofenceEvent.synthetic_run_id == run.id))
    ).scalars().all()
    assert event_rows
    for e in event_rows:
        assert e.is_synthetic
        attendance = next(a for a in attendance_rows if a.id == e.attendance_id)
        assert e.employee_id == attendance.employee_id

    # T9: at least one row somewhere carries a non-null anomaly label given
    # the rates above over 10 sessions with a fixed seed.
    labeled_attendance = [a for a in attendance_rows if a.synthetic_anomaly_type is not None]
    labeled_breaks = [b for b in break_rows if b.synthetic_anomaly_type is not None]
    assert labeled_attendance or labeled_breaks


@pytest.mark.asyncio
async def test_generation_failure_rolls_back_everything_and_marks_run_failed(
    client, db_session, caplog, unique_email, monkeypatch
):
    _, employee_id, _ = await _setup_employee_with_geofence(client, db_session, caplog, unique_email)
    service = WorkforceIntelligenceService(db_session)

    async def _boom(self, rows):
        raise RuntimeError("simulated mid-batch DB failure")

    # Attendance/BreakPeriod rows are already flushed inside the SAVEPOINT by
    # the time GeofenceEvent's bulk insert blows up - this is exactly the
    # "process killed mid-batch" scenario T2 exists to guard.
    monkeypatch.setattr(GeofenceEventRepository, "bulk_create_synthetic", _boom)

    with pytest.raises(SyntheticGenerationError):
        await service.generate_synthetic_data(
            requested_by=None,
            employee_ids=[uuid.UUID(employee_id)],
            date_range_start=date(2026, 2, 2),
            date_range_end=date(2026, 2, 6),
            anomaly_config={},
            seed=1,
        )

    attendance_rows = (
        await db_session.execute(
            select(Attendance).where(Attendance.employee_id == uuid.UUID(employee_id))
        )
    ).scalars().all()
    # Zero synthetic Attendance rows survive - the real check-in from setup
    # (if any) is untouched, but no partial synthetic batch remains.
    assert all(not a.is_synthetic for a in attendance_rows)

    all_runs = (await db_session.execute(select(SyntheticDataRun))).scalars().all()
    assert len(all_runs) == 1
    assert all_runs[0].status == SyntheticDataRunStatus.FAILED
    assert "simulated mid-batch DB failure" in all_runs[0].error_message

    breaks = (await db_session.execute(select(BreakPeriod))).scalars().all()
    events = (await db_session.execute(select(GeofenceEvent))).scalars().all()
    assert all(not b.is_synthetic for b in breaks)
    assert all(not e.is_synthetic for e in events)


@pytest.mark.asyncio
async def test_missed_checkout_never_collides_with_real_open_session(
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
    assert check_in.status_code == 201

    service = WorkforceIntelligenceService(db_session)
    run = await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[uuid.UUID(employee_id)],
        date_range_start=date(2026, 1, 5),
        date_range_end=date(2026, 1, 16),
        anomaly_config={"missed_checkout": 0.5},
        seed=99,
    )
    assert run.status == SyntheticDataRunStatus.COMPLETED

    open_sessions = (
        await db_session.execute(
            select(Attendance).where(
                Attendance.employee_id == uuid.UUID(employee_id),
                Attendance.check_out_at.is_(None),
            )
        )
    ).scalars().all()
    # Only the real check-in from setup is open - no synthetic row was ever
    # allowed to also be open for this employee (uq_attendance_one_open_session
    # is workforce-wide, not scoped to is_synthetic).
    assert len(open_sessions) == 1
    assert open_sessions[0].is_synthetic is False


@pytest.mark.asyncio
async def test_empty_employee_scope_rejected_before_any_run_row_is_created(
    client, db_session, caplog, unique_email
):
    service = WorkforceIntelligenceService(db_session)
    with pytest.raises(SyntheticConfigError):
        await service.generate_synthetic_data(
            requested_by=None,
            employee_ids=[],
            date_range_start=date(2026, 2, 1),
            date_range_end=date(2026, 2, 5),
            anomaly_config={},
            seed=1,
        )

    runs = (await db_session.execute(select(SyntheticDataRun))).scalars().all()
    assert runs == []


@pytest.mark.asyncio
async def test_employee_without_active_geofence_rejected_before_any_run_row_is_created(
    client, db_session, caplog, unique_email
):
    """HR onboards an employee under a department but never assigns a
    geofence - generation has no location to anchor synthetic check-ins to."""
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    employee = await _onboard_employee(client, hr_headers, f"nogeofence-{unique_email}")

    service = WorkforceIntelligenceService(db_session)
    with pytest.raises(SyntheticConfigError):
        await service.generate_synthetic_data(
            requested_by=None,
            employee_ids=[uuid.UUID(employee["id"])],
            date_range_start=date(2026, 2, 1),
            date_range_end=date(2026, 2, 5),
            anomaly_config={},
            seed=1,
        )

    runs = (await db_session.execute(select(SyntheticDataRun))).scalars().all()
    assert runs == []
