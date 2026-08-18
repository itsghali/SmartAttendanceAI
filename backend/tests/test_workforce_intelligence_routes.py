"""PLAN.md Sprint 5 (workforce_intelligence routes): API-level tests for the
Module 1+2 HTTP surface — permission gating (T4), request bounds (T5),
idempotency (T10), and the read endpoints needed to spot-check output.
"""

import uuid
from datetime import date

import pytest

from tests.test_attendance import _make_hr_manager, _onboard_employee
from tests.test_problem_reports import _make_supervisor

WINDOW_START = date(2026, 1, 5)  # Monday
WINDOW_END = date(2026, 3, 30)  # ~12 weeks


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
async def test_generate_then_get_run_round_trip(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)

    resp = await client.post(
        "/workforce-intelligence/synthetic-data/generate",
        json={
            "employee_ids": [str(employee_id)],
            "date_range_start": str(WINDOW_START),
            "date_range_end": str(WINDOW_END),
            "anomaly_config": {"late_arrival": 0.1},
            "seed": 1,
        },
        headers=hr_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["row_counts"]["attendance"] > 0

    get_resp = await client.get(
        f"/workforce-intelligence/synthetic-data/{body['id']}", headers=hr_headers
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_generate_with_same_idempotency_key_does_not_duplicate(
    client, db_session, caplog, unique_email
):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)
    payload = {
        "employee_ids": [str(employee_id)],
        "date_range_start": str(WINDOW_START),
        "date_range_end": str(WINDOW_END),
        "anomaly_config": {},
        "seed": 2,
        "idempotency_key": f"key-{unique_email}",
    }

    first = await client.post("/workforce-intelligence/synthetic-data/generate", json=payload, headers=hr_headers)
    second = await client.post("/workforce-intelligence/synthetic-data/generate", json=payload, headers=hr_headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["row_counts"] == second.json()["row_counts"]


@pytest.mark.asyncio
async def test_generate_rejects_empty_scope_and_oversized_range(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)

    empty_scope = await client.post(
        "/workforce-intelligence/synthetic-data/generate",
        json={
            "employee_ids": [],
            "date_range_start": str(WINDOW_START),
            "date_range_end": str(WINDOW_END),
            "seed": 3,
        },
        headers=hr_headers,
    )
    assert empty_scope.status_code == 422

    oversized_range = await client.post(
        "/workforce-intelligence/synthetic-data/generate",
        json={
            "employee_ids": [str(uuid.uuid4())],
            "date_range_start": "2020-01-01",
            "date_range_end": "2026-01-01",
            "seed": 3,
        },
        headers=hr_headers,
    )
    assert oversized_range.status_code == 422


@pytest.mark.asyncio
async def test_rebuild_then_get_baseline_round_trip(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)

    gen_resp = await client.post(
        "/workforce-intelligence/synthetic-data/generate",
        json={
            "employee_ids": [str(employee_id)],
            "date_range_start": str(WINDOW_START),
            "date_range_end": str(WINDOW_END),
            "anomaly_config": {},
            "seed": 9,
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
    assert rebuild_resp.status_code == 200, rebuild_resp.text
    assert rebuild_resp.json()["built"] == [str(employee_id)]
    assert rebuild_resp.json()["skipped_insufficient_history"] == []

    baseline_resp = await client.get(
        f"/workforce-intelligence/baselines/{employee_id}", headers=hr_headers
    )
    assert baseline_resp.status_code == 200
    assert baseline_resp.json()["employee_id"] == str(employee_id)
    assert "checkin_time_of_day_minutes" in baseline_resp.json()["metric_stats"]


@pytest.mark.asyncio
async def test_get_baseline_404_for_unknown_employee(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    resp = await client.get(
        f"/workforce-intelligence/baselines/{uuid.uuid4()}", headers=hr_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_supervisor_forbidden_from_all_four_endpoints(client, db_session, caplog, unique_email):
    supervisor_access = await _make_supervisor(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {supervisor_access}"}
    run_id = uuid.uuid4()
    employee_id = uuid.uuid4()

    generate = await client.post(
        "/workforce-intelligence/synthetic-data/generate",
        json={
            "employee_ids": [str(employee_id)],
            "date_range_start": str(WINDOW_START),
            "date_range_end": str(WINDOW_END),
            "seed": 1,
        },
        headers=headers,
    )
    get_run = await client.get(f"/workforce-intelligence/synthetic-data/{run_id}", headers=headers)
    rebuild = await client.post(
        "/workforce-intelligence/baselines/rebuild",
        json={
            "employee_ids": [str(employee_id)],
            "window_start": str(WINDOW_START),
            "window_end": str(WINDOW_END),
        },
        headers=headers,
    )
    get_baseline = await client.get(
        f"/workforce-intelligence/baselines/{employee_id}", headers=headers
    )

    assert generate.status_code == 403
    assert get_run.status_code == 403
    assert rebuild.status_code == 403
    assert get_baseline.status_code == 403
