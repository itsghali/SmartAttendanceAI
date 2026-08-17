import enum
import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GeofenceEventType(str, enum.Enum):
    ENTER = "enter"
    EXIT = "exit"
    RETURN = "return"


class GeofenceEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "geofence_events"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    attendance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable + SET NULL: geofences can be deleted mid-shift (same precedent as
    # Attendance.check_in_geofence_id) — the event history must survive that.
    geofence_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("geofences.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[GeofenceEventType] = mapped_column(Enum(GeofenceEventType), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # Workforce Intelligence provenance — mirrors Attendance's columns of the
    # same name, see attendance.py for the full rationale.
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    synthetic_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("synthetic_data_runs.id", ondelete="SET NULL"), nullable=True
    )
    synthetic_anomaly_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    employee: Mapped["Employee"] = relationship()  # noqa: F821
    geofence: Mapped["Geofence | None"] = relationship()  # noqa: F821

    __table_args__ = (
        # Every read of this table is "this attendance's events, in order"
        # (refresh_geofence_events, get_latest_for_attendance, the eager-loaded
        # Attendance.geofence_events relationship) — without this index each of
        # those is a full table scan once event volume grows past a handful of
        # test rows.
        Index("ix_geofence_events_attendance_created", "attendance_id", "created_at"),
        Index("ix_geofence_events_synthetic_run", "synthetic_run_id"),
    )
