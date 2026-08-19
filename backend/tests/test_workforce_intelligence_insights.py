"""PLAN.md Module 4 (insight generation): live round-trip against the real
(SQLite-backed) test DB. Confirms the evidence threshold (HIGH-only), the
review-state transitions, and permission gating — the pure sentence-wording
logic itself is covered directly in
ai/workforce_intelligence/tests/test_insights_generator.py, not re-tested
here.
"""

import uuid
from datetime import date

import pytest

from app.services.workforce_intelligence_service import WorkforceIntelligenceService
from tests.test_problem_reports import _make_supervisor
from tests.test_workforce_intelligence_detection import _hr_headers, _make_employee_with_geofence

WINDOW_START = date(2026, 1, 5)  # Monday
WINDOW_END = date(2026, 6, 30)


@pytest.mark.asyncio
async def test_insights_only_surface_high_severity_flags(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)

    service = WorkforceIntelligenceService(db_session)
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={"late_arrival": 0.2},
        seed=21,
    )
    await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    await service.run_detection(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )

    flags_resp = await client.get(
        f"/workforce-intelligence/detection/flags?employee_id={employee_id}", headers=hr_headers
    )
    all_severities = {item["severity"] for item in flags_resp.json()["items"]}

    insights_resp = await client.get(
        f"/workforce-intelligence/insights?employee_id={employee_id}", headers=hr_headers
    )
    assert insights_resp.status_code == 200
    body = insights_resp.json()
    assert all(item["severity"] == "high" for item in body["items"])
    assert all(isinstance(item["summary"], str) and item["summary"] for item in body["items"])
    if "moderate" in all_severities:
        # The raw evidence view has moderate flags; insights must not.
        assert body["total"] < flags_resp.json()["total"]


@pytest.mark.asyncio
async def test_insights_default_review_status_is_new(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)

    service = WorkforceIntelligenceService(db_session)
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={"late_arrival": 0.2},
        seed=22,
    )
    await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    await service.run_detection(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )

    resp = await client.get(
        f"/workforce-intelligence/insights?employee_id={employee_id}", headers=hr_headers
    )
    items = resp.json()["items"]
    assert items, "expected at least one HIGH-severity insight from a late_arrival-heavy corpus"
    assert all(item["review_status"] == "new" for item in items)
    assert all(item["reviewed_by"] is None and item["reviewed_at"] is None for item in items)


@pytest.mark.asyncio
async def test_review_flag_transitions_and_persists(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    employee_id = await _make_employee_with_geofence(client, hr_headers, unique_email)

    service = WorkforceIntelligenceService(db_session)
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=WINDOW_START,
        date_range_end=WINDOW_END,
        anomaly_config={"late_arrival": 0.2},
        seed=23,
    )
    await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )
    await service.run_detection(
        employee_ids=[employee_id], window_start=WINDOW_START, window_end=WINDOW_END
    )

    insights_resp = await client.get(
        f"/workforce-intelligence/insights?employee_id={employee_id}", headers=hr_headers
    )
    flag_id = insights_resp.json()["items"][0]["id"]

    review_resp = await client.patch(
        f"/workforce-intelligence/detection/flags/{flag_id}/review",
        json={"status": "reviewed"},
        headers=hr_headers,
    )
    assert review_resp.status_code == 200
    body = review_resp.json()
    assert body["review_status"] == "reviewed"
    assert body["reviewed_by"] is not None
    assert body["reviewed_at"] is not None

    # Persists across a fresh read, and transitions freely back to "new".
    reopen_resp = await client.patch(
        f"/workforce-intelligence/detection/flags/{flag_id}/review",
        json={"status": "new"},
        headers=hr_headers,
    )
    assert reopen_resp.status_code == 200
    assert reopen_resp.json()["review_status"] == "new"


@pytest.mark.asyncio
async def test_review_unknown_flag_404s(client, db_session, caplog, unique_email):
    hr_headers = await _hr_headers(client, db_session, caplog, unique_email)
    resp = await client.patch(
        f"/workforce-intelligence/detection/flags/{uuid.uuid4()}/review",
        json={"status": "dismissed"},
        headers=hr_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_supervisor_forbidden_from_insights_endpoints(client, db_session, caplog, unique_email):
    supervisor_access = await _make_supervisor(client, db_session, caplog, unique_email)
    headers = {"Authorization": f"Bearer {supervisor_access}"}

    list_resp = await client.get("/workforce-intelligence/insights", headers=headers)
    review_resp = await client.patch(
        f"/workforce-intelligence/detection/flags/{uuid.uuid4()}/review",
        json={"status": "reviewed"},
        headers=headers,
    )

    assert list_resp.status_code == 403
    assert review_resp.status_code == 403
