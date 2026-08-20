"""NotificationService — Requirement 1 (persistent + email notifications)
and its dedup/aggregation rules. Uses a fake EmailBackend-shaped spy instead
of touching real SMTP (mirrors ConsoleEmailBackend's shape, see
app/services/email_service.py), and constructs EmployeeDeviationFlag rows
directly rather than through the full synthetic-data/detection pipeline —
that pipeline is already covered by test_workforce_intelligence_detection.py
and its synthetic rows would be excluded from notifications anyway (see
WorkforceIntelligenceService.run_detection's is_synthetic filter)."""

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.models.attendance import Attendance, AttendanceStatus
from app.models.employee_deviation_flag import DeviationSeverity, EmployeeDeviationFlag
from app.models.notification import EmailStatus, Notification
from app.models.user import User
from app.repositories.employee_repository import EmployeeRepository
from app.services.notification_service import NotificationService
from tests.test_attendance import _make_hr_manager, _onboard_employee

OCCURRED = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
DETECTED = datetime(2026, 3, 2, 2, 0, tzinfo=timezone.utc)


class FakeEmailService:
    def __init__(self, fail_for: set[str] | None = None):
        self.sent: list[tuple[str, str, str]] = []
        self._fail_for = fail_for or set()

    def send_workforce_intelligence_alert(self, to: str, subject: str, body: str) -> None:
        if to in self._fail_for:
            raise RuntimeError("smtp exploded")
        self.sent.append((to, subject, body))


async def _setup_employee_and_recipient(client, db_session, caplog, unique_email):
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

    employees_by_id = {employee_id: await EmployeeRepository(db_session).get_by_id(employee_id)}
    return employee_id, attendance.id, recipient, employees_by_id


def _make_flag(
    *,
    employee_id,
    attendance_id,
    metric="break_duration_minutes",
    observed_value=81.0,
    severity=DeviationSeverity.HIGH,
    self_z=6.1,
    is_synthetic=False,
) -> EmployeeDeviationFlag:
    return EmployeeDeviationFlag(
        employee_id=employee_id,
        attendance_id=attendance_id,
        metric=metric,
        occurred_at=OCCURRED,
        observed_value=observed_value,
        self_mean=32.0,
        self_std=8.0,
        self_z=self_z,
        self_n=24,
        peer_mean=35.0,
        peer_std=10.0,
        peer_z=4.6,
        peer_n=120,
        severity=severity,
        window_start=date(2025, 12, 1),
        window_end=date(2026, 3, 2),
        detected_at=DETECTED,
        is_synthetic=is_synthetic,
    )


@pytest.mark.asyncio
async def test_high_severity_creates_notification_and_sends_immediately(
    client, db_session, caplog, unique_email
):
    employee_id, attendance_id, recipient, employees_by_id = await _setup_employee_and_recipient(
        client, db_session, caplog, unique_email
    )
    flag = _make_flag(employee_id=employee_id, attendance_id=attendance_id)
    db_session.add(flag)
    await db_session.flush()

    fake_email = FakeEmailService()
    result = await NotificationService(db_session, fake_email).notify_new_flags(
        [flag], employees_by_id
    )
    assert result["created"] == 1
    assert result["emailed_immediately"] == 1
    assert len(fake_email.sent) == 1
    to, subject, body = fake_email.sent[0]
    assert to == recipient.email
    assert "Break Duration" in subject

    notification = (
        await db_session.execute(
            select(Notification).where(Notification.recipient_user_id == recipient.id)
        )
    ).scalar_one()
    assert notification.email_status == EmailStatus.SENT
    assert notification.email_sent_at is not None
    assert notification.is_read is False
    assert notification.severity == DeviationSeverity.HIGH


@pytest.mark.asyncio
async def test_moderate_severity_is_aggregated_not_sent_immediately(
    client, db_session, caplog, unique_email
):
    employee_id, attendance_id, recipient, employees_by_id = await _setup_employee_and_recipient(
        client, db_session, caplog, unique_email
    )
    flag = _make_flag(
        employee_id=employee_id,
        attendance_id=attendance_id,
        severity=DeviationSeverity.MODERATE,
        self_z=2.8,
    )
    db_session.add(flag)
    await db_session.flush()

    fake_email = FakeEmailService()
    result = await NotificationService(db_session, fake_email).notify_new_flags(
        [flag], employees_by_id
    )
    assert result["created"] == 1
    assert result["emailed_immediately"] == 0
    assert fake_email.sent == []

    notification = (
        await db_session.execute(
            select(Notification).where(Notification.recipient_user_id == recipient.id)
        )
    ).scalar_one()
    assert notification.email_status == EmailStatus.PENDING_DIGEST


@pytest.mark.asyncio
async def test_send_pending_digests_bundles_moderate_notifications(
    client, db_session, caplog, unique_email
):
    employee_id, attendance_id, recipient, employees_by_id = await _setup_employee_and_recipient(
        client, db_session, caplog, unique_email
    )
    flags = [
        _make_flag(
            employee_id=employee_id,
            attendance_id=attendance_id,
            metric="break_count",
            observed_value=5.0,
            severity=DeviationSeverity.MODERATE,
            self_z=2.7,
        ),
        _make_flag(
            employee_id=employee_id,
            attendance_id=attendance_id,
            metric="geofence_exit_count",
            observed_value=4.0,
            severity=DeviationSeverity.MODERATE,
            self_z=2.9,
        ),
    ]
    for f in flags:
        db_session.add(f)
    await db_session.flush()

    fake_email = FakeEmailService()
    service = NotificationService(db_session, fake_email)
    await service.notify_new_flags(flags, employees_by_id)
    assert fake_email.sent == []  # nothing sent yet, both pending_digest

    digest_result = await service.send_pending_digests()
    assert digest_result["recipients"] == 1
    assert digest_result["notifications"] == 2
    assert len(fake_email.sent) == 1
    _, subject, body = fake_email.sent[0]
    assert "2" in subject

    rows = (
        (
            await db_session.execute(
                select(Notification).where(Notification.recipient_user_id == recipient.id)
            )
        )
        .scalars()
        .all()
    )
    assert all(n.email_status == EmailStatus.SENT for n in rows)


@pytest.mark.asyncio
async def test_duplicate_flag_on_rerun_does_not_renotify(
    client, db_session, caplog, unique_email
):
    """Simulates WorkforceIntelligenceService.run_detection's own
    delete-and-recreate rebuild cycle: same real occurrence, a brand new
    flag row/id, same (employee, attendance, metric, observed_value)."""
    employee_id, attendance_id, recipient, employees_by_id = await _setup_employee_and_recipient(
        client, db_session, caplog, unique_email
    )
    flag_day_1 = _make_flag(employee_id=employee_id, attendance_id=attendance_id)
    db_session.add(flag_day_1)
    await db_session.flush()

    fake_email = FakeEmailService()
    service = NotificationService(db_session, fake_email)
    first = await service.notify_new_flags([flag_day_1], employees_by_id)
    assert first["created"] == 1

    # rebuild: old flag row is gone, a new one with a new id but identical
    # occurrence fields takes its place.
    await db_session.delete(flag_day_1)
    await db_session.flush()
    flag_day_2 = _make_flag(employee_id=employee_id, attendance_id=attendance_id)
    db_session.add(flag_day_2)
    await db_session.flush()
    assert flag_day_2.id != flag_day_1.id

    second = await service.notify_new_flags([flag_day_2], employees_by_id)
    assert second["created"] == 0
    assert len(fake_email.sent) == 1  # still just the one email from day 1

    count = (
        await db_session.execute(
            select(Notification).where(Notification.recipient_user_id == recipient.id)
        )
    ).scalars().all()
    assert len(count) == 1


@pytest.mark.asyncio
async def test_two_distinct_anomalous_breaks_same_session_both_notified(
    client, db_session, caplog, unique_email
):
    employee_id, attendance_id, recipient, employees_by_id = await _setup_employee_and_recipient(
        client, db_session, caplog, unique_email
    )
    flags = [
        _make_flag(employee_id=employee_id, attendance_id=attendance_id, observed_value=81.0),
        _make_flag(employee_id=employee_id, attendance_id=attendance_id, observed_value=95.0),
    ]
    for f in flags:
        db_session.add(f)
    await db_session.flush()

    fake_email = FakeEmailService()
    result = await NotificationService(db_session, fake_email).notify_new_flags(
        flags, employees_by_id
    )
    assert result["created"] == 2
    assert len(fake_email.sent) == 2


@pytest.mark.asyncio
async def test_email_disabled_still_creates_db_notification_but_no_send(
    client, db_session, caplog, unique_email, monkeypatch
):
    from app.config.settings import get_settings

    monkeypatch.setattr(
        get_settings(), "workforce_intelligence_email_notifications_enabled", False
    )
    employee_id, attendance_id, recipient, employees_by_id = await _setup_employee_and_recipient(
        client, db_session, caplog, unique_email
    )
    flag = _make_flag(employee_id=employee_id, attendance_id=attendance_id)
    db_session.add(flag)
    await db_session.flush()

    fake_email = FakeEmailService()
    result = await NotificationService(db_session, fake_email).notify_new_flags(
        [flag], employees_by_id
    )
    assert result["created"] == 1
    assert fake_email.sent == []

    notification = (
        await db_session.execute(
            select(Notification).where(Notification.recipient_user_id == recipient.id)
        )
    ).scalar_one()
    assert notification.email_status == EmailStatus.DISABLED


@pytest.mark.asyncio
async def test_send_failure_marks_failed_but_does_not_raise(
    client, db_session, caplog, unique_email
):
    employee_id, attendance_id, recipient, employees_by_id = await _setup_employee_and_recipient(
        client, db_session, caplog, unique_email
    )
    flag = _make_flag(employee_id=employee_id, attendance_id=attendance_id)
    db_session.add(flag)
    await db_session.flush()

    fake_email = FakeEmailService(fail_for={recipient.email})
    result = await NotificationService(db_session, fake_email).notify_new_flags(
        [flag], employees_by_id
    )
    assert result["created"] == 1
    assert result["emailed_immediately"] == 0

    notification = (
        await db_session.execute(
            select(Notification).where(Notification.recipient_user_id == recipient.id)
        )
    ).scalar_one()
    assert notification.email_status == EmailStatus.FAILED


@pytest.mark.asyncio
async def test_notification_read_unread_state_and_scoping(
    client, db_session, caplog, unique_email
):
    employee_id, attendance_id, recipient, employees_by_id = await _setup_employee_and_recipient(
        client, db_session, caplog, unique_email
    )
    flag = _make_flag(employee_id=employee_id, attendance_id=attendance_id)
    db_session.add(flag)
    await db_session.flush()

    service = NotificationService(db_session, FakeEmailService())
    await service.notify_new_flags([flag], employees_by_id)

    notification = (
        await db_session.execute(
            select(Notification).where(Notification.recipient_user_id == recipient.id)
        )
    ).scalar_one()
    assert await service.count_unread(recipient.id) == 1

    # A different user cannot mark someone else's notification read.
    other_id = uuid.uuid4()
    assert await service.mark_read(notification.id, other_id) is None

    marked = await service.mark_read(notification.id, recipient.id)
    assert marked.is_read is True
    assert marked.read_at is not None
    assert await service.count_unread(recipient.id) == 0

    # Idempotent second call.
    marked_again = await service.mark_read(notification.id, recipient.id)
    assert marked_again.is_read is True


@pytest.mark.asyncio
async def test_synthetic_flags_never_notified(client, db_session, caplog, unique_email):
    """End-to-end through the real pipeline (generate_synthetic_data ->
    rebuild_baselines -> run_detection), the way the daily scheduler
    actually calls it — every flag this produces is_synthetic=True, and
    WorkforceIntelligenceService.run_detection must filter all of them out
    before calling NotificationService.notify_new_flags."""
    from datetime import date as date_

    from app.services.workforce_intelligence_service import WorkforceIntelligenceService
    from tests.test_attendance import _onboard_employee as _onboard

    hr_access = await _make_hr_manager(client, db_session, caplog, unique_email)
    hr_headers = {"Authorization": f"Bearer {hr_access}"}
    geofence_resp = await client.post(
        "/geofences",
        json={"name": "HQ", "center_latitude": 33.5731, "center_longitude": -7.5898, "radius_meters": 150},
        headers=hr_headers,
    )
    assert geofence_resp.status_code == 201
    onboarded = await _onboard(client, hr_headers, f"emp-{unique_email}", hire_date="2025-01-01")
    employee_id = uuid.UUID(onboarded["id"])

    window_start = date_(2026, 1, 5)
    window_end = date_(2026, 6, 30)
    service = WorkforceIntelligenceService(db_session)
    await service.generate_synthetic_data(
        requested_by=None,
        employee_ids=[employee_id],
        date_range_start=window_start,
        date_range_end=window_end,
        anomaly_config={"late_arrival": 0.3},
        seed=7,
    )
    rebuild_result = await service.rebuild_baselines(
        employee_ids=[employee_id], window_start=window_start, window_end=window_end
    )
    assert employee_id in rebuild_result["built"]
    detect_result = await service.run_detection(
        employee_ids=[employee_id], window_start=window_start, window_end=window_end
    )
    assert sum(detect_result["flag_counts"].values()) > 0  # sanity: detection did produce flags

    notifications = (await db_session.execute(select(Notification))).scalars().all()
    assert notifications == []
