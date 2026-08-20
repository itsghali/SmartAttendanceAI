"""Notification Service — Requirement 1 of the Workforce Intelligence
notification/insight-presentation work: turns a batch of freshly-persisted
EmployeeDeviationFlag rows into (a) persistent, per-recipient Notification
rows the dashboard's notification center reads, and (b) email sends for the
external channel, subject to the severity-based aggregation rule below.

Reuses the existing severity values (DeviationSeverity.HIGH/MODERATE) rather
than inventing a new scoring system, and the existing EmailService/
EmailBackend abstraction (SMTP or console, env-configured, never hardcoded
credentials) rather than a new email stack.

Deduplication: see Notification's docstring and _dedupe_key below — flag
rows are NOT a stable identity (WorkforceIntelligenceService.run_detection
deletes and recreates them on every rerun), so dedup keys off the underlying
attendance occurrence instead.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.models.employee import Employee
from app.models.employee_deviation_flag import DeviationSeverity, EmployeeDeviationFlag
from app.models.mixins import utcnow
from app.models.notification import EmailStatus, Notification
from app.models.user import User
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService

_AI_DIR = Path(__file__).resolve().parents[3] / "ai"
if str(_AI_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_DIR))

from workforce_intelligence.insights import generator as insights_generator  # noqa: E402

logger = logging.getLogger("app.notifications")

# Only HIGH gets an immediate individual email — MODERATE is aggregated into
# the once-daily digest (Requirement 1: "DO NOT send an email for every
# low-level anomaly individually"). Reuses DeviationSeverity as-is.
IMMEDIATE_EMAIL_SEVERITIES = frozenset({DeviationSeverity.HIGH})

WORKFORCE_INTELLIGENCE_READ_PERMISSION = "workforce_intelligence:read"


def _dedupe_key(employee_id: uuid.UUID, attendance_id: uuid.UUID, metric: str, observed_value: float) -> str:
    """Identity of a real anomaly occurrence, stable across a flag-row
    rebuild (see Notification's docstring): the flag's own id churns every
    time run_detection reruns for a window containing this occurrence, but
    (employee, attendance session, metric, observed value) does not — it
    traces back to the real attendance row, not the ephemeral flag row."""
    raw = f"{employee_id}:{attendance_id}:{metric}:{round(observed_value, 4)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class NotificationService:
    def __init__(self, session: AsyncSession, email_service: EmailService | None = None):
        self._session = session
        self._notifications = NotificationRepository(session)
        self._users = UserRepository(session)
        self._email = email_service or EmailService()

    def _deep_link(self, employee_id: uuid.UUID) -> str:
        settings = get_settings()
        return f"{settings.frontend_base_url}/anomaly-detection?employee_id={employee_id}"

    async def notify_new_flags(
        self,
        flags: list[EmployeeDeviationFlag],
        employees_by_id: dict[uuid.UUID, Employee],
    ) -> dict:
        """Called from WorkforceIntelligenceService.run_detection right
        after a batch of flags is bulk_create'd, in the same transaction.
        Creates at most one Notification per (recipient, real occurrence) —
        see _dedupe_key — and sends HIGH-severity email immediately.
        MODERATE-severity notifications are left `pending_digest`;
        send_pending_digests (called once at the end of the scheduler's
        daily job) is what actually emails those."""
        if not flags:
            return {"created": 0, "emailed_immediately": 0}

        recipients = await self._users.list_active_recipients_for_permission(
            WORKFORCE_INTELLIGENCE_READ_PERMISSION
        )
        if not recipients:
            return {"created": 0, "emailed_immediately": 0}

        settings = get_settings()
        now = utcnow()
        created = 0
        emailed = 0

        for flag in flags:
            employee = employees_by_id.get(flag.employee_id)
            employee_name = employee.user.full_name if employee is not None else "an employee"

            presentation = insights_generator.build_presentation(
                metric=flag.metric,
                observed_value=flag.observed_value,
                self_mean=flag.self_mean,
                self_std=flag.self_std,
                self_z=flag.self_z,
                self_n=flag.self_n,
                peer_mean=flag.peer_mean,
                peer_std=flag.peer_std,
                peer_z=flag.peer_z,
                peer_n=flag.peer_n,
                severity=flag.severity.value,
                occurred_at=flag.occurred_at,
                detected_at=flag.detected_at,
            )
            dedupe_key = _dedupe_key(
                flag.employee_id, flag.attendance_id, flag.metric, flag.observed_value
            )
            immediate = flag.severity in IMMEDIATE_EMAIL_SEVERITIES
            deep_link = self._deep_link(flag.employee_id)

            for recipient in recipients:
                row = {
                    "recipient_user_id": recipient.id,
                    "employee_id": flag.employee_id,
                    "deviation_flag_id": flag.id,
                    "dedupe_key": dedupe_key,
                    "metric": flag.metric,
                    "severity": flag.severity,
                    "title": presentation["title"],
                    "summary": presentation["summary"],
                    "evidence": presentation["evidence"],
                    "recommended_action": presentation["recommended_action"],
                    "occurred_at": flag.occurred_at,
                    "detected_at": flag.detected_at,
                    # MODERATE lands as pending_digest immediately; HIGH
                    # starts not_applicable and is overwritten below once
                    # the actual send is attempted (sent/failed/disabled).
                    "email_status": (
                        EmailStatus.NOT_APPLICABLE if immediate else EmailStatus.PENDING_DIGEST
                    ),
                }

                notification = await self._notifications.create_if_new(row)
                if notification is None:
                    continue  # already notified this recipient for this occurrence
                created += 1

                if not immediate:
                    continue
                if not settings.workforce_intelligence_email_notifications_enabled:
                    notification.email_status = EmailStatus.DISABLED
                    continue

                subject, body = insights_generator.render_email(
                    presentation, employee_name=employee_name, deep_link=deep_link
                )
                try:
                    self._email.send_workforce_intelligence_alert(recipient.email, subject, body)
                    notification.email_status = EmailStatus.SENT
                    notification.email_sent_at = now
                    emailed += 1
                except Exception:
                    logger.exception(
                        "failed to send workforce-intelligence alert to %s", recipient.email
                    )
                    notification.email_status = EmailStatus.FAILED

        await self._session.flush()
        return {"created": created, "emailed_immediately": emailed}

    async def send_pending_digests(self) -> dict:
        """Once-daily aggregation send (Requirement 1) — bundles every
        recipient's still-pending_digest notifications (MODERATE severity,
        or a HIGH one that lost the email-enabled race, see above) into one
        email each, instead of one email per anomaly. Called by
        app/core/scheduler.py's daily job, after run_detection has already
        populated notifications for that run."""
        settings = get_settings()
        by_recipient = await self._notifications.list_pending_digest_by_recipient()
        if not by_recipient:
            return {"recipients": 0, "notifications": 0}

        recipient_ids = list(by_recipient.keys())
        recipients_by_id: dict[uuid.UUID, User] = {}
        for recipient_id in recipient_ids:
            user = await self._session.get(User, recipient_id)
            if user is not None:
                recipients_by_id[recipient_id] = user

        now = utcnow()
        sent_recipients = 0
        sent_notifications = 0

        for recipient_id, notifications in by_recipient.items():
            recipient = recipients_by_id.get(recipient_id)
            if recipient is None or not recipient.is_active:
                continue

            if not settings.workforce_intelligence_email_notifications_enabled:
                for n in notifications:
                    n.email_status = EmailStatus.DISABLED
                continue

            presentations = [
                {
                    "title": n.title,
                    "summary": n.summary,
                    "evidence": n.evidence,
                }
                for n in notifications
            ]
            deep_link = f"{settings.frontend_base_url}/anomaly-detection"
            subject, body = insights_generator.render_digest_email(
                presentations, deep_link=deep_link
            )
            try:
                self._email.send_workforce_intelligence_alert(recipient.email, subject, body)
                await self._notifications.mark_digest_sent(notifications, now)
                sent_recipients += 1
                sent_notifications += len(notifications)
            except Exception:
                logger.exception(
                    "failed to send workforce-intelligence digest to %s", recipient.email
                )
                for n in notifications:
                    n.email_status = EmailStatus.FAILED

        await self._session.flush()
        return {"recipients": sent_recipients, "notifications": sent_notifications}

    async def list_for_user(
        self, user_id: uuid.UUID, unread_only: bool, limit: int, offset: int
    ) -> tuple[list[Notification], int]:
        return await self._notifications.list_paginated(user_id, unread_only, limit, offset)

    async def count_unread(self, user_id: uuid.UUID) -> int:
        return await self._notifications.count_unread(user_id)

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification | None:
        notification = await self._notifications.get_by_id(notification_id)
        if notification is None or notification.recipient_user_id != user_id:
            return None
        return await self._notifications.mark_read(notification, utcnow())
