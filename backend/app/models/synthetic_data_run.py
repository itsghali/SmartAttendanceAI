import enum
import uuid
from datetime import date

from sqlalchemy import JSON, Date, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SyntheticDataRunStatus(str, enum.Enum):
    REQUESTED = "requested"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SyntheticDataRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Audit + provenance record for one synthetic-data-generation batch.

    Every Attendance/BreakPeriod/GeofenceEvent row this run writes is tagged
    with synthetic_run_id, so an entire batch is purgeable with one
    WHERE synthetic_run_id = <id> and never mixes silently with real data.
    """

    __tablename__ = "synthetic_data_runs"

    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    employee_scope: Mapped[list] = mapped_column(JSON, nullable=False)
    date_range_start: Mapped[date] = mapped_column(Date, nullable=False)
    date_range_end: Mapped[date] = mapped_column(Date, nullable=False)
    anomaly_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[SyntheticDataRunStatus] = mapped_column(
        Enum(SyntheticDataRunStatus),
        default=SyntheticDataRunStatus.REQUESTED,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    row_counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    requested_by_user: Mapped["User | None"] = relationship()  # noqa: F821
