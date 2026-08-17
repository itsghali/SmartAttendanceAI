import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BreakSource(str, enum.Enum):
    MANUAL = "manual"
    # Auto-started by MonitoringService on a debounced geofence EXIT, and
    # auto-ended on the matching RETURN (or on checkout if RETURN never
    # comes) — see MonitoringService.record_ping. Unlike a manual break,
    # pings keep being processed while this is open so RETURN can still be
    # detected; the CNIL no-tracking-during-break rule only applies to
    # MANUAL breaks, which are employee-initiated rest time.
    GEOFENCE_EXIT = "geofence_exit"


class BreakPeriod(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "break_periods"

    attendance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[BreakSource] = mapped_column(
        Enum(BreakSource), nullable=False, server_default=BreakSource.MANUAL.name
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

    # Workforce Intelligence provenance — mirrors Attendance's columns of the
    # same name, see attendance.py for the full rationale.
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    synthetic_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("synthetic_data_runs.id", ondelete="SET NULL"), nullable=True
    )
    synthetic_anomaly_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_break_periods_attendance_id", "attendance_id"),
        Index("ix_break_periods_synthetic_run", "synthetic_run_id"),
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
