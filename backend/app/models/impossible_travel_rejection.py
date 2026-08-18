import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ImpossibleTravelRejection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Audit trail for check-ins blocked by the impossible-travel gate
    (attendance_service._check_impossible_travel_or_raise). The gate itself
    is a pre-existing, unmodified hard block (attendance_service.py) — this
    table only records that a rejection happened, since the block left zero
    DB trace before this (PLAN.md Module 3 / Candidate 6). Written and
    committed BEFORE ImpossibleTravelError is raised (see the call site) so
    the row survives even though get_db() rolls back the rest of the
    request's transaction on the exception — same "small independent commit"
    precedent WorkforceIntelligenceService uses for SyntheticDataRun status
    transitions. No is_synthetic column: this only ever fires on the live
    check-in path, which the impossible-travel gate itself already excludes
    synthetic rows from (PLAN.md T0)."""

    __tablename__ = "impossible_travel_rejections"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    # The prior closed session the rejected check-in was compared against.
    # Nullable + SET NULL: must not block Attendance deletion/retention work
    # on this audit row's existence.
    prior_attendance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("attendance_records.id", ondelete="SET NULL"), nullable=True
    )
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    elapsed_hours: Mapped[float] = mapped_column(Float, nullable=False)
    implied_speed_kmh: Mapped[float] = mapped_column(Float, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)

    employee: Mapped["Employee"] = relationship()  # noqa: F821

    __table_args__ = (
        Index("ix_impossible_travel_rejections_employee_created", "employee_id", "created_at"),
    )
