import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.settings import get_settings
from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    LATE = "late"
    REMOTE = "remote"


class Attendance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "attendance_records"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)

    check_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Nullable: manual/backfilled entries (HR correction, no device GPS involved)
    # have no coordinates. Self-service check-in always supplies real ones —
    # enforced at the request-schema level, not the DB level.
    check_in_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in_accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_in_geofence_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("geofences.id", ondelete="SET NULL"), nullable=True
    )

    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_out_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_out_accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    check_out_geofence_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("geofences.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus), default=AttendanceStatus.PRESENT, nullable=False
    )
    is_manual_entry: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str] = mapped_column(String(1000), default="")

    # Continuous geofence monitoring state (mutable, DB-backed so it survives
    # across multi-worker deployments — see geofence_events for the immutable
    # ENTER/EXIT/RETURN audit log; these three columns are only the debounce
    # counters, never queried for "current status" — that's derived from the
    # latest geofence_events row).
    last_ping_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outside_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        # One row is one SITE SESSION (check-in → check-out), not one day. An
        # employee moving between chantiers checks in and out several times a
        # day, so the old UNIQUE (employee_id, attendance_date) was wrong: it
        # capped a worker at one site per day and — because Morocco is UTC+1,
        # where the UTC date rolls at 01:00 local — also made check-out
        # impossible for a night shift that crossed midnight.
        #
        # What must still be impossible is holding TWO OPEN sessions at once,
        # which is what this partial unique index enforces. It is the backstop
        # for two simultaneous check-in requests that both pass the service-level
        # guard before either commits; check_in() rescues the IntegrityError.
        Index(
            "uq_attendance_one_open_session",
            "employee_id",
            unique=True,
            postgresql_where=text("check_out_at IS NULL"),
            sqlite_where=text("check_out_at IS NULL"),
        ),
        Index("ix_attendance_employee_checkin", "employee_id", "check_in_at"),
    )

    employee: Mapped["Employee"] = relationship()  # noqa: F821
    check_in_geofence: Mapped["Geofence | None"] = relationship(  # noqa: F821
        foreign_keys=[check_in_geofence_id]
    )
    check_out_geofence: Mapped["Geofence | None"] = relationship(  # noqa: F821
        foreign_keys=[check_out_geofence_id]
    )
    breaks: Mapped[list["BreakPeriod"]] = relationship(  # noqa: F821
        back_populates="attendance", order_by="BreakPeriod.break_start_at"
    )
    geofence_events: Mapped[list["GeofenceEvent"]] = relationship(  # noqa: F821
        order_by="GeofenceEvent.created_at"
    )

    @property
    def monitoring_status(self) -> str | None:
        """Read-time derivation, not a stored column — there is nothing to
        migrate and nothing to keep in sync.

        Killing the app mid-shift previously left outside_streak/status frozen
        at whatever they were, forever, with nothing distinguishing "still
        inside" from "phone is dead" — the single largest wage-integrity gap
        found in the geofencing MVP review. `None` for a closed session
        (staleness is moot once checked out).
        """
        if self.check_out_at is not None:
            return None
        if self.check_in_geofence_id is None:
            return "not_monitored"
        if any(b.break_end_at is None for b in self.breaks):
            # Pings are intentionally paused for the duration of a break (see
            # monitoring_service.record_ping) — that gap must never read as
            # staleness.
            return "on_break"
        # 3x the ping interval mirrors the exit-debounce margin elsewhere in
        # this module — one or two missed pings is normal jitter, not a dead
        # device.
        threshold_seconds = get_settings().geofence_ping_interval_seconds * 3
        baseline = self.last_ping_at or self.check_in_at
        if baseline.tzinfo is None:
            # SQLite (used in tests) round-trips DateTime(timezone=True) as
            # naive; Postgres does not. Normalize rather than let the two
            # backends disagree on whether this raises.
            baseline = baseline.replace(tzinfo=timezone.utc)
        if (utcnow() - baseline).total_seconds() > threshold_seconds:
            return "stale"
        return "live"
