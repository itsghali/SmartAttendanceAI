import enum
import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GeofenceBoundaryType(str, enum.Enum):
    CIRCLE = "circle"
    POLYGON = "polygon"


class Geofence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "geofences"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )  # null = global/company-wide geofence
    boundary_type: Mapped[GeofenceBoundaryType] = mapped_column(
        Enum(GeofenceBoundaryType), default=GeofenceBoundaryType.CIRCLE, nullable=False
    )
    # Circle fields — required when boundary_type == CIRCLE, null for POLYGON.
    center_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Polygon field — required when boundary_type == POLYGON, null for CIRCLE.
    # list[{"latitude": float, "longitude": float}]. Plain JSON, no PostGIS —
    # same call as the circle's Float lat/lng (see TODOS.md deferred item).
    polygon_points: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    department: Mapped["Department | None"] = relationship()  # noqa: F821
