import uuid

from sqlalchemy import ForeignKey, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import decrypt_embedding, encrypt_embedding
from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FaceProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "face_profiles"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # DB column name/type unchanged ("embedding", JSON) — JSON columns can
    # hold a plain string value, not just arrays, so storing the Fernet
    # token here needed no schema migration, only a data one (see
    # database/migrations for the backfill). The Python attribute is
    # `embedding_encrypted`; `.embedding` below is the transparent
    # plaintext view every existing caller (face_service.py) already uses —
    # encryption is invisible above the model, matching the "application-layer
    # encryption at the repository boundary" plan (PLAN.md item 5), just one
    # layer lower (the model itself) so no call site needed to change.
    embedding_encrypted: Mapped[str] = mapped_column("embedding", JSON, nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    enrollment_photo_count: Mapped[int] = mapped_column(Integer, nullable=False)

    employee: Mapped["Employee"] = relationship()  # noqa: F821

    @property
    def embedding(self) -> list[float]:
        """Raises cryptography.fernet.InvalidToken if no configured key can
        decrypt the stored value — callers must catch this (see
        FaceProfileCorruptedError in face_service.py), not let it 500."""
        return decrypt_embedding(self.embedding_encrypted)

    @embedding.setter
    def embedding(self, value: list[float]) -> None:
        self.embedding_encrypted = encrypt_embedding(value)
