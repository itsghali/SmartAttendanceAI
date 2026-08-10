from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidCredentialsError,
    InvalidOTPError,
    InvalidRefreshTokenError,
    UserAlreadyExistsError,
    UserInactiveError,
    UserNotVerifiedError,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)
from app.models.device import Device
from app.models.otp import OTPPurpose
from app.models.user import User
from app.repositories.device_repository import DeviceRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailService
from app.services.otp_service import OTPService

DEFAULT_ROLE_NAME = "employee"


class AuthService:
    def __init__(self, session: AsyncSession, email_service: EmailService | None = None):
        self._session = session
        self._users = UserRepository(session)
        self._roles = RoleRepository(session)
        self._devices = DeviceRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)
        self._otp = OTPService(session, email_service)

    async def register(self, email: str, password: str, full_name: str) -> User:
        if await self._users.get_by_email(email) is not None:
            raise UserAlreadyExistsError(f"user with email {email} already exists")

        role = await self._roles.get_by_name(DEFAULT_ROLE_NAME)
        if role is None:
            raise RuntimeError(
                f"default role '{DEFAULT_ROLE_NAME}' is not seeded — run the RBAC seed script"
            )

        user = await self._users.create(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role_id=role.id,
        )
        user.role = role
        await self._otp.issue(user, OTPPurpose.EMAIL_VERIFICATION)
        return user

    async def verify_email(self, email: str, code: str) -> User:
        user = await self._users.get_by_email(email)
        if user is None or not await self._otp.verify(user, OTPPurpose.EMAIL_VERIFICATION, code):
            raise InvalidOTPError("invalid or expired verification code")
        await self._users.mark_verified(user)
        return user

    async def login(
        self,
        email: str,
        password: str,
        device_identifier: str | None,
        device_name: str | None,
        platform: str | None,
    ) -> tuple[User, str, str]:
        user = await self._users.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError("invalid email or password")
        if not user.is_active:
            raise UserInactiveError("account is deactivated")
        if not user.is_verified:
            raise UserNotVerifiedError("account email is not verified")

        device: Device | None = None
        if device_identifier:
            device = await self._devices.get_by_identifier(user.id, device_identifier)
            if device is None:
                device = await self._devices.create(
                    user.id, device_identifier, device_name or "", platform or ""
                )
            else:
                await self._devices.touch(device)

        access_token = create_access_token(str(user.id), {"role": user.role.name})
        raw_refresh, refresh_hash, expires_at = generate_refresh_token()
        await self._refresh_tokens.create(
            user.id, refresh_hash, expires_at, device.id if device else None
        )
        return user, access_token, raw_refresh

    async def refresh(self, raw_refresh_token: str) -> tuple[str, str]:
        token = await self._refresh_tokens.get_by_hash(hash_opaque_token(raw_refresh_token))
        if token is None or not token.is_active:
            raise InvalidRefreshTokenError("refresh token is invalid, expired, or revoked")

        user = await self._users.get_by_id(token.user_id)
        if user is None or not user.is_active:
            raise InvalidRefreshTokenError("refresh token is invalid, expired, or revoked")

        await self._refresh_tokens.revoke(token)
        new_raw, new_hash, new_expires_at = generate_refresh_token()
        await self._refresh_tokens.create(user.id, new_hash, new_expires_at, token.device_id)

        access_token = create_access_token(str(user.id), {"role": user.role.name})
        return access_token, new_raw

    async def logout(self, raw_refresh_token: str) -> None:
        token = await self._refresh_tokens.get_by_hash(hash_opaque_token(raw_refresh_token))
        if token is not None and token.is_active:
            await self._refresh_tokens.revoke(token)

    async def forgot_password(self, email: str) -> None:
        user = await self._users.get_by_email(email)
        if user is None:
            return  # don't leak account existence
        await self._otp.issue(user, OTPPurpose.PASSWORD_RESET)

    async def reset_password(self, email: str, code: str, new_password: str) -> None:
        user = await self._users.get_by_email(email)
        if user is None or not await self._otp.verify(user, OTPPurpose.PASSWORD_RESET, code):
            raise InvalidOTPError("invalid or expired reset code")
        await self._users.update_password(user, hash_password(new_password))
        await self._refresh_tokens.revoke_all_for_user(user.id)

    async def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(current_password, user.hashed_password):
            raise InvalidCredentialsError("current password is incorrect")
        await self._users.update_password(user, hash_password(new_password))
        await self._refresh_tokens.revoke_all_for_user(user.id)
