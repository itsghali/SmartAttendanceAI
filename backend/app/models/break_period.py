import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BreakPeriod(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "break_periods"

    attendance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False
    )
    break_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    break_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Nullable for the same reason the check-in/check-out coordinate columns are:
    # rows written before this shipped have no position, and manual entries never
    # will. Mirrors the Attendance column layout deliberately — same names, same
    # order — so the two tables read the same way.
    start_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_geofence_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("geofences.id", ondelete="SET NULL"), nullable=True
    )

    end_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_geofence_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("geofences.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_break_periods_attendance_id", "attendance_id"),
        # Two near-simultaneous start_break() requests both pass the
        # get_open_for_attendance() check before either commits — this is the
        # real backstop, mirroring uq_attendance_one_open_session on Attendance.
        Index(
            "uq_break_period_one_open_per_attendance",
            "attendance_id",
            unique=True,
            postgresql_where=text("break_end_at IS NULL"),
            sqlite_where=text("break_end_at IS NULL"),
        ),
    )

    attendance: Mapped["Attendance"] = relationship(back_populates="breaks")  # noqa: F821
