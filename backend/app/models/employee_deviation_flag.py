import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class DeviationSeverity(str, enum.Enum):
    MODERATE = "moderate"
    HIGH = "high"


class ReviewStatus(str, enum.Enum):
    """Module 4's minimal reviewer-action state (PLAN.md CEO-phase review,
    Candidate 1) — deliberately NOT the fuller case-resolution system
    (escalation/assignment/SLA) TODOS.md already has open for geofence
    exceptions; that stays a shared, deferred question."""

    NEW = "new"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"


class EmployeeDeviationFlag(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Module 3 output: one row per (employee, metric, session-or-break
    occurrence) whose value deviates from that employee's own baseline by
    more than ai/workforce_intelligence/detection/detector.py's z-score
    threshold. Self-baseline deviation is the trigger (the sub-problem's own
    "deviation from an employee's own baseline" framing); peer_mean/peer_std/
    peer_z are stored as CONTEXT for a human reviewer only — they do not
    gate whether a flag is emitted. A true company-wide-event suppression
    (comparing the peer group's CURRENT period against its OWN prior period)
    would need a second, temporal peer baseline this pass doesn't have —
    named as a real limitation, not silently built as a shaky heuristic; see
    AI-CHANGELOG.md's Module 3 entry.

    self_std/peer_std of 0.0 makes self_z/peer_z undefined (degenerate
    variance, e.g. break_count that's been exactly 1 every day) — detector.py
    flags a mismatch from a zero-variance baseline directly rather than
    dividing by zero, and self_z/peer_z stay NULL on that row (severity is
    still set, from the degenerate-mismatch rule, not from a null z).

    is_synthetic/synthetic_run_id mirror Attendance/BreakPeriod/GeofenceEvent
    (PLAN.md T0/T1 precedent) — a flag derived from synthetic input rows must
    stay excluded from any future real-employee-facing read path by default.
    """

    __tablename__ = "employee_deviation_flags"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    # The session this flag is about (for a break-level flag, the parent
    # session — BreakPeriod isn't linked separately, same anchor Module 1/2
    # already use for every per-session signal).
    attendance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_value: Mapped[float] = mapped_column(Float, nullable=False)
    self_mean: Mapped[float] = mapped_column(Float, nullable=False)
    self_std: Mapped[float] = mapped_column(Float, nullable=False)
    self_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    peer_mean: Mapped[float] = mapped_column(Float, nullable=False)
    peer_std: Mapped[float] = mapped_column(Float, nullable=False)
    peer_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[DeviationSeverity] = mapped_column(Enum(DeviationSeverity), nullable=False)
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Provenance — see class docstring.
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    synthetic_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("synthetic_data_runs.id", ondelete="SET NULL"), nullable=True
    )
    # The label the source row was generated with, if any (T9-style) — lets
    # the detection-accuracy validation test measure recall/false-positive
    # rate against known ground truth, same idea as Attendance
    # .synthetic_anomaly_type.
    synthetic_anomaly_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Module 4 reviewer-action state — see ReviewStatus docstring.
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus), default=ReviewStatus.NEW, nullable=False
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    employee: Mapped["Employee"] = relationship()  # noqa: F821

    __table_args__ = (
        Index(
            "ix_employee_deviation_flags_employee_window",
            "employee_id",
            "window_start",
            "window_end",
        ),
        Index("ix_employee_deviation_flags_synthetic_run", "synthetic_run_id"),
    )
