import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mixins import utcnow
from app.models.otp import OTPCode, OTPPurpose


class OTPRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self, user_id: uuid.UUID, purpose: OTPPurpose, code_hash: str, expires_at: datetime
    ) -> OTPCode:
        otp = OTPCode(
            user_id=user_id, purpose=purpose, code_hash=code_hash, expires_at=expires_at
        )
        self._session.add(otp)
        await self._session.flush()
        return otp

    async def get_latest_active(self, user_id: uuid.UUID, purpose: OTPPurpose) -> OTPCode | None:
        stmt = (
            select(OTPCode)
            .where(
                OTPCode.user_id == user_id,
                OTPCode.purpose == purpose,
                OTPCode.consumed_at.is_(None),
                OTPCode.expires_at > utcnow(),
            )
            .order_by(OTPCode.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def increment_attempts(self, otp: OTPCode) -> None:
        otp.attempts += 1
        await self._session.flush()

    async def consume(self, otp: OTPCode) -> None:
        otp.consumed_at = utcnow()
        await self._session.flush()
