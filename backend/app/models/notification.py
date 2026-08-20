import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, String, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.employee_deviation_flag import DeviationSeverity
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EmailStatus:
    """Plain string constants, not a DB enum — new values (e.g. a future
    "throttled") shouldn't need a migration the way DeviationSeverity does,
    and there's no cross-table reuse pressure the way that enum has."""

    NOT_APPLICABLE = "not_applicable"
    PENDING_DIGEST = "pending_digest"
    SENT = "sent"
    DISABLED = "disabled"
    FAILED = "failed"


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per (recipient, anomaly occurrence). Denormalized on purpose:
    employee_id/metric/title/summary/evidence are snapshotted at creation
    time rather than joined live off EmployeeDeviationFlag, because
    WorkforceIntelligenceService.run_detection deletes and recreates flag
    rows for a (employee, window) on every rerun (see that method's
    docstring) — a notification must keep rendering correctly after its
    originating flag row is long gone. deviation_flag_id is kept as a
    best-effort link to the CURRENT live flag (for the review-status
    shortcut), not as the source of truth for display.

    dedupe_key identifies the real-world occurrence — derived from
    (employee_id, attendance_id, metric, observed_value), all of which are
    stable across a flag-row rebuild since they trace back to the actual
    attendance record, not the ephemeral flag row's own id. See
    NotificationService._dedupe_key.
    """

    __tablename__ = "notifications"

    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    deviation_flag_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employee_deviation_flags.id", ondelete="SET NULL"), nullable=True
    )

    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[DeviationSeverity] = mapped_column(Enum(DeviationSeverity), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    recommended_action: Mapped[list] = mapped_column(JSON, nullable=False)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    email_status: Mapped[str] = mapped_column(
        String(20), default=EmailStatus.NOT_APPLICABLE, nullable=False
    )
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    employee: Mapped["Employee"] = relationship()  # noqa: F821

    __table_args__ = (
        UniqueConstraint("recipient_user_id", "dedupe_key", name="uq_notifications_recipient_dedupe"),
        Index("ix_notifications_recipient_read", "recipient_user_id", "is_read"),
        Index("ix_notifications_email_status", "email_status"),
    )
