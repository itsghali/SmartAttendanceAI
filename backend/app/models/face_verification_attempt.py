import enum
import uuid

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FaceVerificationFailureReason(str, enum.Enum):
    NO_FACE = "no_face"
    MULTIPLE_FACES = "multiple_faces"
    INVALID_IMAGE = "invalid_image"
    NOT_ENROLLED = "not_enrolled"
    LOW_SIMILARITY = "low_similarity"
    LIVENESS_FAILED = "liveness_failed"
    MODEL_UNAVAILABLE = "model_unavailable"
    PROFILE_CORRUPTED = "profile_corrupted"


class FaceVerificationAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Audit trail for verify attempts. Never stores the uploaded image —
    only the computed scores and outcome, to keep the biometric-data surface
    to a minimum. Scores are never returned to the client (see face_service.py)
    — they exist here purely for the threshold pilot-tuning work TODOS.md
    flags as required before trusting face_similarity_threshold in production."""

    __tablename__ = "face_verification_attempts"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    liveness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[FaceVerificationFailureReason | None] = mapped_column(
        Enum(FaceVerificationFailureReason), nullable=True
    )

    employee: Mapped["Employee"] = relationship()  # noqa: F821

    __table_args__ = (
        Index("ix_face_verification_attempts_employee_created", "employee_id", "created_at"),
    )
