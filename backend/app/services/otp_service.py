from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.security import generate_otp_code, hash_otp_code
from app.models.mixins import utcnow
from app.models.otp import OTPPurpose
from app.models.user import User
from app.repositories.otp_repository import OTPRepository
from app.services.email_service import EmailService


class OTPService:
    def __init__(
        self,
        session: AsyncSession,
        email_service: EmailService | None = None,
    ):
        self._repo = OTPRepository(session)
        self._email_service = email_service or EmailService()
        self._settings = get_settings()

    async def issue(self, user: User, purpose: OTPPurpose) -> None:
        code = generate_otp_code()
        expires_at = utcnow() + timedelta(minutes=self._settings.otp_expire_minutes)
        await self._repo.create(user.id, purpose, hash_otp_code(code), expires_at)
        self._email_service.send_otp_email(user.email, code, purpose.value)

    async def verify(self, user: User, purpose: OTPPurpose, code: str) -> bool:
        otp = await self._repo.get_latest_active(user.id, purpose)
        if otp is None or not otp.is_valid:
            return False
        if hash_otp_code(code) != otp.code_hash:
            await self._repo.increment_attempts(otp)
            return False
        await self._repo.consume(otp)
        return True
