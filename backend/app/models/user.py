import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # GOVERNANCE.md Section 2 (consent/notice) — set once, the first time this
    # user dismisses WorkforceIntelligenceNoticeModal (mobile). A notice
    # record, not a consent gate: nothing in the Workforce Intelligence data
    # flow reads or branches on this field, it exists purely so the org has a
    # durable record notice was actually given (a device-local flag would be
    # lost on reinstall, defeating the point).
    workforce_intelligence_notice_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("roles.id"), nullable=False)
    role: Mapped["Role"] = relationship(back_populates="users")  # noqa: F821

    devices: Mapped[list["Device"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    otp_codes: Mapped[list["OTPCode"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
