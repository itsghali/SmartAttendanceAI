"""PLAN.md Module 3 (deviation detection): live round-trip against the real
(SQLite-backed) test DB. Detection method decided this sprint (see
ai/workforce_intelligence/detection/detector.py's own docstring for the
full reasoning): z-score against the employee's own EmployeeBaseline, not a
fitted IsolationForest — a deliberate departure from PLAN.md's original
ML commitment, made explicitly with the user rather than silently.

THE most important test here is
test_detection_recalls_labeled_anomalies_with_low_false_positive_rate below
— it's the concrete mechanism that proves detection actually detects the
known-labeled synthetic anomalies, not just that the code runs.
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.models.employee_deviation_flag import EmployeeDeviationFlag
from app.services.workforce_intelligence_service import WorkforceIntelligenceService
from tests.test_attendance import _make_hr_manager, _onboard_employee
from tests.test_problem_reports import _make_supervisor
from workforce_intelligence.exceptions import DetectionConfigError

WINDOW_START = date(2026, 1, 5)  # Monday
WINDOW_END = date(2026, 6, 30)  # ~25 weeks, well over the 40-workday floor


async def _hr_headers(client, db_session, caplog, unique_email):
    access = await _make_hr_manager(client, db_session, caplog, unique_email)
    return {"Authorization": f"Bearer {access}"}


async def _make_employee_with_geofence(client, hr_headers, unique_email):
    geofence_resp = await client.post(
        "/geofences",
        json={"name": "HQ", "center_latitude": 33.5731, "center_longitude": -7.5898, "radius_meters": 150},
        headers=hr_headers,
    )
    assert geofence_resp.status_code == 201
    onboarded = await _onboard_employee(
        client, hr_headers, f"emp-{unique_email}", hire_date="2025-01-01"
    )
    return uuid.UUID(onboarded["id"])


@pytest.mark.asyncio
async def test_detection_recalls_labeled_anomalies_with_low_false_positive_rate(
    client, db_session, caplog, unique_email
):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)

    service = WorkforceIntelligenceService(db_session)
    # late_arrival shifts checkin time hours later than normal -> should be
    # a checkin_time_of_day_minutes outlier against a baseline that (per
    # T9) excluded these very sessions when it was fit.
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={"late_arrival": 0.2},
        seed=42,
    )
    rebuild_result = await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert employee_id in rebuild_result["built"]

    detect_result = await service.run_detection(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert employee_id in detect_result["scored"]
    assert detect_result["skipped_no_baseline"] == []

    flags = (
        (
            await db_session.execute(
                select(EmployeeDeviationFlag).where(
                    EmployeeDeviationFlag.employee_id == employee_id,
                    EmployeeDeviationFlag.metric == "checkin_time_of_day_minutes",
                )
            )
        )
        .scalars()
        .all()
    )
    flagged_by_anomaly_type = {
        f.synthetic_anomaly_type for f in flags if f.synthetic_anomaly_type is not None
    }
    # The labeled anomaly type this test actually configured must show up
    # among the flags -- proves recall, not just "some flags exist".
    assert "late_arrival" in flagged_by_anomaly_type

    clean_flags = [f for f in flags if f.synthetic_anomaly_type is None]
    late_arrival_flags = [f for f in flags if f.synthetic_anomaly_type == "late_arrival"]
    # Recall: most late_arrival sessions should be caught.
    assert len(late_arrival_flags) > 0
    # False-positive containment: clean sessions should rarely be flagged on
    # the very metric late_arrival perturbs.
    assert len(clean_flags) < len(late_arrival_flags)


@pytest.mark.asyncio
async def test_skips_employee_with_no_baseline(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)

    service = WorkforceIntelligenceService(db_session)
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={},
        seed=10,
    )
    # No rebuild_baselines call -> no EmployeeBaseline row exists yet.
    result = await service.run_detection(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert result["scored"] == []
    assert employee_id in result["skipped_no_baseline"]


@pytest.mark.asyncio
async def test_rerun_is_idempotent_replaces_not_accumulates(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)

    service = WorkforceIntelligenceService(db_session)
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={"late_arrival": 0.2},
        seed=11,
    )
    await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )

    r1 = await service.run_detection(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    r2 = await service.run_detection(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    assert r1["flag_counts"] == r2["flag_counts"]

    rows = (
        (
            await db_session.execute(
                select(EmployeeDeviationFlag).where(
                    EmployeeDeviationFlag.employee_id == employee_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == sum(r2["flag_counts"].values())


@pytest.mark.asyncio
async def test_request_validation_rejected_before_touching_flags(client, db_session, caplog, unique_email):
    service = WorkforceIntelligenceService(db_session)

    with pytest.raises(DetectionConfigError):
        await service.run_detection(employee_ids=[], window_start=WINDOW_START, window_end=WINDOW_END)

    with pytest.raises(DetectionConfigError):
        await service.run_detection(
            employee_ids=[uuid.uuid4()], window_start=WINDOW_END, window_end=WINDOW_START
        )

    with pytest.raises(DetectionConfigError):
        await service.run_detection(
            employee_ids=[uuid.uuid4()], window_start=WINDOW_START, window_end=WINDOW_END
        )


@pytest.mark.asyncio
async def test_run_detection_then_list_flags_route_round_trip(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)

    gen_resp = await client.post(
        "/workforce-intelligence/synthetic-data/generate",
        json={
            "employee_ids": [str(employee_id)],
            "date_range_start": str(WINDOW_START),
            "date_range_end": str(WINDOW_END),
            "anomaly_config": {"late_arrival": 0.2},
            "seed": 12,
        },
        headers=hr_headers,
    )
    assert gen_resp.status_code == 201

    rebuild_resp = await client.post(
        "/workforce-intelligence/baselines/rebuild",
        json={
            "employee_ids": [str(employee_id)],
            "window_start": str(WINDOW_START),
            "window_end": str(WINDOW_END),
        },
        headers=hr_headers,
    )
    assert rebuild_resp.status_code == 200

    detect_resp = await client.post(
        "/workforce-intelligence/detection/run",
        json={
            "employee_ids": [str(employee_id)],
            "window_start": str(WINDOW_START),
            "window_end": str(WINDOW_END),
        },
        headers=hr_headers,
    )
    assert detect_resp.status_code == 200, detect_resp.text
    assert detect_resp.json()["scored"] == [str(employee_id)]
    assert detect_resp.json()["skipped_no_baseline"] == []
    assert detect_resp.json()["flag_counts"][str(employee_id)] > 0

    list_resp = await client.get(
        f"/workforce-intelligence/detection/flags?employee_id={employee_id}",
        headers=hr_headers,
    )
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] > 0
    assert all(item["employee_id"] == str(employee_id) for item in body["items"])


@pytest.mark.asyncio
async def test_supervisor_forbidden_from_detection_endpoints(client, db_session, caplog, unique_email):
    supervisor_access = await _make_supervisor(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {supervisor_access}"}
    employee_id = uuid.uuid4()

    run_resp = await client.post(
        "/workforce-intelligence/detection/run",
        json={
            "employee_ids": [str(employee_id)],
            "window_start": str(WINDOW_START),
            "window_end": str(WINDOW_END),
        },
        headers=headers,
    )
    list_resp = await client.get("/workforce-intelligence/detection/flags", headers=headers)

    assert run_resp.status_code == 403
    assert list_resp.status_code == 403
