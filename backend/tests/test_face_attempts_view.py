import logging
import uuid

import pytest

from app.config.settings import get_settings
from app.models.face_verification_attempt import FaceVerificationFailureReason
from app.repositories.face_repository import FaceRepository
from tests.conftest import login, promote_to_role, register_and_verify


@pytest.fixture(autouse=True)
def _face_verification_off(monkeypatch):
    """Same reasoning as test_geofence_history.py — .env's
    FACE_VERIFICATION_ENABLED=true would otherwise gate every onboarding
    check-in this file's setup helper does; irrelevant to what's tested
    here (the attempts-history *view*, not the verify pipeline itself)."""
    monkeypatch.setattr(get_settings(), "face_verification_enabled", False)


async def _make_role(client, db_session, caplog, email: str, role_name: str) -> str:
    caplog.set_level(logging.INFO, logger="app.email")
    await register_and_verify(client, caplog, email)
    await promote_to_role(db_session, email, role_name)
    return await login(client, email)


async def _onboard_employee(client, hr_headers, email: str) -> str:
    resp = await client.post(
        "/employees",
        json={
            "email": email,
            "full_name": "Face Attempts Employee",
            "password": "TempPass123",
            "hire_date": "2026-01-15",
        },
        headers=hr_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_face_attempts_view_excludes_scores_and_includes_reason(
    client, db_session, caplog, unique_email
):
    hr_access = await _make_role(client, db_session, caplog, unique_email, "hr_manager")
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    employee_id = await _onboard_employee(client, hr_headers, f"hire-{unique_email}")

    repo = FaceRepository(db_session)
    await repo.record_attempt(
        employee_id=uuid.UUID(employee_id),
        similarity_score=0.42,
        liveness_score=0.91,
        passed=False,
        failure_reason=FaceVerificationFailureReason.LOW_SIMILARITY,
    )
    await repo.record_attempt(
        employee_id=uuid.UUID(employee_id),
        similarity_score=0.88,
        liveness_score=0.95,
        passed=True,
        failure_reason=None,
    )
    await db_session.commit()

    resp = await client.get(f"/face/attempts/{employee_id}", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2

    failed_row = next(r for r in body["items"] if not r["passed"])
    assert failed_row["failure_reason"] == "low_similarity"
    passed_row = next(r for r in body["items"] if r["passed"])
    assert passed_row["failure_reason"] is None

    for row in body["items"]:
        assert "similarity_score" not in row
        assert "liveness_score" not in row


@pytest.mark.asyncio
async def test_face_attempts_empty_for_employee_with_no_attempts(
    client, db_session, caplog, unique_email
):
    hr_access = await _make_role(client, db_session, caplog, unique_email, "hr_manager")
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    employee_id = await _onboard_employee(client, hr_headers, f"hire-{unique_email}")

    resp = await client.get(f"/face/attempts/{employee_id}", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_supervisor_cannot_view_face_attempts(client, db_session, caplog, unique_email):
    hr_access = await _make_role(client, db_session, caplog, unique_email, "hr_manager")
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    employee_id = await _onboard_employee(client, hr_headers, f"hire-{unique_email}")

    supervisor_email = f"supervisor-{unique_email}"
    supervisor_access = await _make_role(
        client, db_session, caplog, supervisor_email, "supervisor"
    )
    supervisor_headers = {"Authorization": f"Bearer {supervisor_access}"}

    resp = await client.get(f"/face/attempts/{employee_id}", headers=supervisor_headers)
    assert resp.status_code == 403, resp.text
