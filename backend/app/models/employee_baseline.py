import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EmployeeBaseline(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Latest computed statistical baseline for one employee.

    One row per employee (unique employee_id) — rebuild upserts in place;
    this row IS the cache, never recomputed live on a read. metric_stats
    shape per metric key (e.g. "checkin_time_of_day_minutes",
    "work_duration_minutes", "break_duration_minutes", "break_count",
    "geofence_exit_count"):
        {
          "self": {"mean": float, "std": float, "n": int},
          "peer": {
            "mean": float, "std": float, "n": int,
            "source": "department" | "company_wide",
            "department_id": str | None
          }
        }
    "peer" falls back to "company_wide" below the minimum department-size
    threshold (see ai/workforce_intelligence/baseline/builder.py); department
    is snapshotted at compute time, not re-resolved live, so a mid-window
    department reassignment doesn't retroactively change past baselines.
    """

    __tablename__ = "employee_baselines"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    metric_stats: Mapped[dict] = mapped_column(JSON, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    employee: Mapped["Employee"] = relationship()  # noqa: F821
