import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProblemReportStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class ProblemReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "problem_reports"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    # Optional — an employee can report a problem generally, not only in
    # reaction to a specific check-in/out/break action. SET NULL rather than
    # CASCADE: the report is evidence of a real complaint and must survive
    # the attendance record it referenced being deleted.
    attendance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("attendance_records.id", ondelete="SET NULL"), nullable=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ProblemReportStatus] = mapped_column(
        Enum(ProblemReportStatus), nullable=False, default=ProblemReportStatus.OPEN
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    employee: Mapped["Employee"] = relationship()  # noqa: F821

    __table_args__ = (
        # HR's list view is always "open ones first" — same reasoning as the
        # geofence_events attendance/created index.
        Index("ix_problem_reports_status_created", "status", "created_at"),
    )
