"""GET/PATCH /notifications — scoped strictly to the caller's own
recipient_user_id (see routes/notifications.py's own docstring on why there
is no dedicated permission code)."""

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.models.attendance import Attendance, AttendanceStatus
from app.models.employee_deviation_flag import DeviationSeverity, EmployeeDeviationFlag
from app.models.user import User
from app.repositories.employee_repository import EmployeeRepository
from app.services.notification_service import NotificationService
from tests.test_attendance import _make_hr_manager, _onboard_employee, login, register_and_verify

OCCURRED = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
DETECTED = datetime(2026, 3, 2, 2, 0, tzinfo=timezone.utc)


class _NoopEmail:
    def send_workforce_intelligence_alert(self, to, subject, body):
        pass


async def _seed_one_notification(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    employee = await _onboard_employee(client, hr_headers, f"emp-{unique_email}")
    employee_id = uuid.UUID(employee["id"])

    recipient = (
        await db_session.execute(select(User).where(User.email == unique_email))
    ).scalar_one()

    attendance = Attendance(
        employee_id=employee_id,
        attendance_date=date(2026, 3, 2),
        check_in_at=OCCURRED,
        status=AttendanceStatus.PRESENT,
        is_synthetic=False,
    )
    db_session.add(attendance)
    await db_session.flush()

    flag = EmployeeDeviationFlag(
        employee_id=employee_id,
        attendance_id=attendance.id,
        metric="break_duration_minutes",
        occurred_at=OCCURRED,
        observed_value=81.0,
        self_mean=32.0,
        self_std=8.0,
        self_z=6.1,
        self_n=24,
        peer_mean=35.0,
        peer_std=10.0,
        peer_z=4.6,
        peer_n=120,
        severity=DeviationSeverity.HIGH,
        window_start=date(2025, 12, 1),
        window_end=date(2026, 3, 2),
        detected_at=DETECTED,
        is_synthetic=False,
    )
    db_session.add(flag)
    await db_session.flush()

    employees_by_id = {employee_id: await EmployeeRepository(db_session).get_by_id(employee_id)}
    await NotificationService(db_session, _NoopEmail()).notify_new_flags([flag], employees_by_id)
    await db_session.commit()
    return hr_headers, recipient


@pytest.mark.asyncio
async def test_list_notifications_scoped_to_caller(client, db_session, caplog, unique_email):
    hr_headers, recipient = await _seed_one_notification(client, db_session, caplog, unique_email)

    resp = await client.get("/notifications", headers=hr_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["title"] == "Unusual Break Duration"
    assert item["is_read"] is False
    assert "self_z" not in item["evidence"]

    # A second, unrelated user sees none of it.
    other_email = f"other-{unique_email}"
    await register_and_verify(client, caplog, other_email)
    other_access = await login(client, other_email)
    other_resp = await client.get(
        "/notifications", headers={"Authorization": f"Bearer {other_access}"}
    )
    assert other_resp.status_code == 200
    assert other_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_unread_count_and_mark_read_roundtrip(client, db_session, caplog, unique_email):
    hr_headers, recipient = await _seed_one_notification(client, db_session, caplog, unique_email)

    unread = await client.get("/notifications/unread-count", headers=hr_headers)
    assert unread.json()["unread_count"] == 1

    listed = await client.get("/notifications", headers=hr_headers)
    notification_id = listed.json()["items"][0]["id"]

    read_resp = await client.patch(f"/notifications/{notification_id}/read", headers=hr_headers)
    assert read_resp.status_code == 200, read_resp.text
    assert read_resp.json()["is_read"] is True

    unread_after = await client.get("/notifications/unread-count", headers=hr_headers)
    assert unread_after.json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_mark_read_unknown_id_404s(client, db_session, caplog, unique_email):
    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    resp = await client.patch(
        f"/notifications/{uuid.uuid4()}/read",
        headers={"Authorization": f"Bearer {hr_access}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unread_only_filter(client, db_session, caplog, unique_email):
    hr_headers, recipient = await _seed_one_notification(client, db_session, caplog, unique_email)
    listed = await client.get("/notifications", headers=hr_headers)
    notification_id = listed.json()["items"][0]["id"]
    await client.patch(f"/notifications/{notification_id}/read", headers=hr_headers)

    resp = await client.get("/notifications?unread_only=true", headers=hr_headers)
    assert resp.json()["total"] == 0

    resp_all = await client.get("/notifications?unread_only=false", headers=hr_headers)
    assert resp_all.json()["total"] == 1
