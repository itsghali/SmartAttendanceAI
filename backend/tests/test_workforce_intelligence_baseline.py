"""PLAN.md Sprint 4 (Module 2 - per-employee/peer-group baselines): live
round-trip against the real (SQLite-backed) test DB, generating a synthetic
corpus (Module 1, already shipped) and rebuilding baselines on top of it
(Module 2, this sprint).

Thresholds this session decided (not yet re-validated against real data,
see PLAN.md's own "hardcoded policy decisions" note):
  MIN_HISTORY_WORKDAYS = 40, MIN_DEPARTMENT_SIZE = 20.
"""

import statistics
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.attendance import Attendance
from app.models.department import Department
from app.models.employee import Employee, EmployeeStatus
from app.models.employee_baseline import EmployeeBaseline
from app.models.geofence import Geofence
from app.models.role import Role
from app.models.user import User
from app.services.workforce_intelligence_service import WorkforceIntelligenceService
from tests.test_attendance import _make_hr_manager, _onboard_employee
from workforce_intelligence.exceptions import BaselineConfigError

WINDOW_START = date(2026, 1, 5)  # Monday
WINDOW_END = date(2026, 6, 30)  # ~25 weeks, well over the 40-workday floor


async def _employee_role_id(db_session):
    role = (await db_session.execute(select(Role).where(Role.name == "employee"))).scalar_one()
    return role.id


async def _make_bare_employee(
    db_session,
    role_id,
    hashed_password,
    *,
    department_id=None,
    status=EmployeeStatus.ACTIVE,
    hire_date=date(2020, 1, 1),
    code_suffix=None,
) -> Employee:
    """Direct-ORM employee creation (no HTTP, no per-call password hash) -
    used for tests that need many employees (department-size threshold) and
    don't need those employees to ever log in."""
    suffix = code_suffix or uuid.uuid4().hex[:10]
    user = User(
        email=f"synthuser-{suffix}@chantier.example",
        hashed_password=hashed_password,
        full_name=f"Synth User {suffix}",
        is_active=True,
        is_verified=True,
        role_id=role_id,
    )
    db_session.add(user)
    await db_session.flush()
    employee = Employee(
        user_id=user.id,
        employee_code=f"SYN-{suffix}",
        department_id=department_id,
        hire_date=hire_date,
        status=status,
    )
    db_session.add(employee)
    await db_session.flush()
    return employee


@pytest.mark.asyncio
async def test_fixed_fixture_round_trip_self_baseline_matches_hand_computed_stats(
    client, db_session, caplog, unique_email
):
    """THE test PLAN.md names as most important: generate a known corpus,
    rebuild, and assert the persisted baseline matches independently
    hand-computed stats from the raw rows - not just "a baseline exists"."""
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    geofence_resp = await client.post(
        "/geofences",
        json={"name": "HQ", "center_latitude": 33.5731, "center_longitude": -7.5898, "radius_meters": 150},
        headers=hr_headers,
    )
    assert geofence_resp.status_code == 201
    onboarded = await _onboard_employee(
        client, hr_headers, f"emp1-{unique_email}", hire_date="2025-01-01"
    )
    employee_id = uuid.UUID(onboarded["id"])

    service = WorkforceIntelligenceService(db_session)
    gen_run = await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={"late_arrival": 0.15},
        seed=4,
    )
    assert gen_run.status.value == "completed"

    result = await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert employee_id in result["built"]
    assert result["skipped_insufficient_history"] == []

    baseline = (
        await db_session.execute(
            select(EmployeeBaseline).where(EmployeeBaseline.employee_id == employee_id)
        )
    ).scalar_one()

    # Hand-compute the expected checkin_time_of_day_minutes stats directly
    # from the raw rows, independent of the builder module, and compare.
    rows = (
        (
            await db_session.execute(
                select(Attendance).where(
                    Attendance.employee_id == employee_id,
                    Attendance.synthetic_anomaly_type.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    expected_minutes = [r.check_in_at.hour * 60 + r.check_in_at.minute for r in rows]
    expected_mean = statistics.fmean(expected_minutes)
    expected_std = statistics.pstdev(expected_minutes)

    self_stats = baseline.metric_stats["checkin_time_of_day_minutes"]["self"]
    assert self_stats["n"] == len(expected_minutes)
    assert self_stats["mean"] == pytest.approx(expected_mean, abs=0.5)
    assert self_stats["std"] == pytest.approx(expected_std, abs=0.5)

    # This employee has no department -> peer group must fall straight to
    # company-wide, never divide-by-near-zero on an undefined department.
    peer_stats = baseline.metric_stats["checkin_time_of_day_minutes"]["peer"]
    assert peer_stats["source"] == "company_wide"
    assert peer_stats["department_id"] is None

    for metric in (
        "work_duration_minutes",
        "break_duration_minutes",
        "break_count",
        "geofence_exit_count",
    ):
        assert metric in baseline.metric_stats
        assert set(baseline.metric_stats[metric]["self"]) == {"mean", "std", "n"}


@pytest.mark.asyncio
async def test_insufficient_history_skips_and_writes_no_baseline_row(
    client, db_session, caplog, unique_email
):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    await client.post(
        "/geofences",
        json={"name": "HQ", "center_latitude": 33.5731, "center_longitude": -7.5898, "radius_meters": 150},
        headers=hr_headers,
    )
    onboarded = await _onboard_employee(
        client, hr_headers, f"emp2-{unique_email}", hire_date="2026-01-01"
    )
    employee_id = uuid.UUID(onboarded["id"])

    service = WorkforceIntelligenceService(db_session)
    # 10 calendar days ~= 7-8 workdays, well under the 40-workday floor.
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=date(2026, 1, 5),
        date_range_end=date(2026, 1, 16),
        anomaly_config={},
        seed=5,
    )

    result = await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=date(2026, 1, 5), window_end=date(2026, 1, 16)
    )
    assert result["built"] == []
    assert employee_id in result["skipped_insufficient_history"]

    baseline = (
        await db_session.execute(
            select(EmployeeBaseline).where(EmployeeBaseline.employee_id == employee_id)
        )
    ).scalar_one_or_none()
    assert baseline is None


@pytest.mark.asyncio
async def test_department_below_min_size_falls_back_chaos_test(client, db_session, caplog, unique_email):
    """Chaos test PLAN.md names explicitly: a tiny department must not
    divide by near-zero variance - it must fall back to company-wide."""
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    await client.post(
        "/geofences",
        json={"name": "HQ", "center_latitude": 33.5731, "center_longitude": -7.5898, "radius_meters": 150},
        headers=hr_headers,
    )
    dept = Department(name=f"Solo Dept {unique_email}")
    db_session.add(dept)
    await db_session.flush()

    role_id = await _employee_role_id(db_session)
    hashed = hash_password("unused")
    solo_employee = await _make_bare_employee(
        db_session, role_id, hashed, department_id=dept.id, hire_date=date(2025, 1, 1)
    )

    service = WorkforceIntelligenceService(db_session)
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[solo_employee.id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={},
        seed=6,
    )
    result = await service.rebuild_baselines(
        employee_ids=[solo_employee.id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert solo_employee.id in result["built"]

    baseline = (
        await db_session.execute(
            select(EmployeeBaseline).where(EmployeeBaseline.employee_id == solo_employee.id)
        )
    ).scalar_one()
    peer = baseline.metric_stats["checkin_time_of_day_minutes"]["peer"]
    assert peer["source"] == "company_wide"


@pytest.mark.asyncio
async def test_department_at_min_size_uses_real_peer_group(client, db_session, caplog, unique_email):
    dept = Department(name=f"Big Dept {unique_email}")
    db_session.add(dept)
    db_session.add(
        Geofence(
            name="HQ",
            center_latitude=33.5731,
            center_longitude=-7.5898,
            radius_meters=150,
        )
    )
    await db_session.flush()

    role_id = await _employee_role_id(db_session)
    hashed = hash_password("unused")
    # 20 headcount clears MIN_DEPARTMENT_SIZE - none need their own history,
    # build_peer_group only checks distinct-employee count in the pool.
    peers = [
        await _make_bare_employee(
            db_session, role_id, hashed, department_id=dept.id, code_suffix=f"peer{i}-{unique_email[:6]}"
        )
        for i in range(19)
    ]
    target = await _make_bare_employee(
        db_session, role_id, hashed, department_id=dept.id, hire_date=date(2025, 1, 1),
        code_suffix=f"target-{unique_email[:6]}",
    )
    assert len(peers) + 1 == 20

    service = WorkforceIntelligenceService(db_session)
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[target.id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={},
        seed=7,
    )
    result = await service.rebuild_baselines(
        employee_ids=[target.id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert target.id in result["built"]

    baseline = (
        await db_session.execute(
            select(EmployeeBaseline).where(EmployeeBaseline.employee_id == target.id)
        )
    ).scalar_one()
    peer = baseline.metric_stats["checkin_time_of_day_minutes"]["peer"]
    assert peer["source"] == "department"
    assert peer["department_id"] == str(dept.id)


@pytest.mark.asyncio
async def test_terminated_employee_skipped_not_built(client, db_session, caplog, unique_email):
    role_id = await _employee_role_id(db_session)
    hashed = hash_password("unused")
    employee = await _make_bare_employee(
        db_session, role_id, hashed, status=EmployeeStatus.TERMINATED, hire_date=date(2025, 1, 1)
    )

    service = WorkforceIntelligenceService(db_session)
    result = await service.rebuild_baselines(
        employee_ids=[employee.id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert result["built"] == []
    assert employee.id in result["skipped_terminated"]

    baseline = (
        await db_session.execute(
            select(EmployeeBaseline).where(EmployeeBaseline.employee_id == employee.id)
        )
    ).scalar_one_or_none()
    assert baseline is None


@pytest.mark.asyncio
async def test_rebuild_is_idempotent_upsert_not_duplicate_rows(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    await client.post(
        "/geofences",
        json={"name": "HQ", "center_latitude": 33.5731, "center_longitude": -7.5898, "radius_meters": 150},
        headers=hr_headers,
    )
    onboarded = await _onboard_employee(
        client, hr_headers, f"emp3-{unique_email}", hire_date="2025-01-01"
    )
    employee_id = uuid.UUID(onboarded["id"])

    service = WorkforceIntelligenceService(db_session)
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={},
        seed=8,
    )

    r1 = await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    r2 = await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert r1["built"] == [employee_id]
    assert r2["built"] == [employee_id]

    rows = (
        (
            await db_session.execute(
                select(EmployeeBaseline).where(EmployeeBaseline.employee_id == employee_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_request_validation_rejected_before_touching_baselines(client, db_session, caplog, unique_email):
    service = WorkforceIntelligenceService(db_session)

    with pytest.raises(BaselineConfigError):
        await service.rebuild_baselines(employee_ids=[], window_start=WINDOW_START, window_end=WINDOW_END)

    with pytest.raises(BaselineConfigError):
        await service.rebuild_baselines(
            employee_ids=[uuid.uuid4()], window_start=WINDOW_END, window_end=WINDOW_START
        )

    with pytest.raises(BaselineConfigError):
        await service.rebuild_baselines(
            employee_ids=[uuid.uuid4()], window_start=WINDOW_START, window_end=WINDOW_END
        )

    count = (await db_session.execute(select(EmployeeBaseline))).scalars().all()
    assert count == []
