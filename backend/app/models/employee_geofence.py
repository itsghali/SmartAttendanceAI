import uuid

from sqlalchemy import ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class EmployeeGeofence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """HR-granted permission for one employee to check in at one specific site,
    on top of (not instead of) the existing department/global scoping."""

    __tablename__ = "employee_geofences"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    geofence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("geofences.id", ondelete="CASCADE"), nullable=False
    )

    employee: Mapped["Employee"] = relationship()  # noqa: F821
    geofence: Mapped["Geofence"] = relationship()  # noqa: F821

    __table_args__ = (
        UniqueConstraint("employee_id", "geofence_id", name="uq_employee_geofence"),
    )
