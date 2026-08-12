import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


def _validate_password_strength(value: str) -> str:
    if len(value) < 8:
        raise ValueError("password must be at least 8 characters")
    if not any(c.isdigit() for c in value):
        raise ValueError("password must contain at least one digit")
    if not any(c.isalpha() for c in value):
        raise ValueError("password must contain at least one letter")
    return value


PRIVILEGED_SIGNUP_ROLES = {"admin", "hr_manager", "super_admin"}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, max_length=50)
    # Web-dashboard-only: request admin/hr/super_admin instead of the default
    # "employee" role. Requires setup_code to match ADMIN_SIGNUP_CODE server-side
    # — see AuthService.register. Mobile signup never sends this.
    role: str | None = Field(default=None)
    setup_code: str | None = Field(default=None, max_length=255)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)

    @field_validator("role")
    @classmethod
    def check_role(cls, value: str | None) -> str | None:
        if value is not None and value not in PRIVILEGED_SIGNUP_ROLES:
            raise ValueError(f"role must be one of {sorted(PRIVILEGED_SIGNUP_ROLES)}")
        return value


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone_number: str | None = None
    role: str
    is_active: bool
    is_verified: bool

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    device_identifier: str | None = Field(default=None, max_length=255)
    device_name: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=50)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def check_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def check_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class DeviceOut(BaseModel):
    id: uuid.UUID
    device_name: str
    platform: str
    is_trusted: bool
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: uuid.UUID
    device_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}
