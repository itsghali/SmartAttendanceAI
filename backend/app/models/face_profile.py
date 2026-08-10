import uuid

from sqlalchemy import ForeignKey, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FaceProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "face_profiles"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # Plain JSON float array, not ARRAY/pgvector — comparison is always one
    # employee's stored embedding vs. one live capture (no similarity search
    # across employees), matching the existing precedent of plain columns over
    # PostGIS at this scale (see TODOS.md geoalchemy2 entry), and keeps the
    # SQLite in-memory test suite working unchanged.
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    enrollment_photo_count: Mapped[int] = mapped_column(Integer, nullable=False)

    employee: Mapped["Employee"] = relationship()  # noqa: F821
