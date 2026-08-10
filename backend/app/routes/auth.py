from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.exceptions import (
    InvalidCredentialsError,
    InvalidOTPError,
    InvalidRefreshTokenError,
    UserAlreadyExistsError,
    UserInactiveError,
    UserNotVerifiedError,
)
from app.core.rate_limit import rate_limit
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
    VerifyEmailRequest,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.name,
        is_active=user.is_active,
        is_verified=user.is_verified,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_db)) -> UserOut:
    try:
        user = await AuthService(session).register(body.email, body.password, body.full_name)
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _user_out(user)


@router.post("/verify-email", response_model=UserOut)
async def verify_email(
    body: VerifyEmailRequest, session: AsyncSession = Depends(get_db)
) -> UserOut:
    try:
        user = await AuthService(session).verify_email(body.email, body.code)
    except InvalidOTPError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _user_out(user)


@router.post(
    "/login", response_model=TokenResponse, dependencies=[Depends(rate_limit("login", 10, 60))]
)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        _, access_token, refresh_token = await AuthService(session).login(
            body.email,
            body.password,
            body.device_identifier,
            body.device_name,
            body.platform,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    except (UserInactiveError, UserNotVerifiedError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, session: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        access_token, refresh_token = await AuthService(session).refresh(body.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, session: AsyncSession = Depends(get_db)) -> None:
    await AuthService(session).logout(body.refresh_token)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("forgot-password", 5, 300))],
)
async def forgot_password(
    body: ForgotPasswordRequest, session: AsyncSession = Depends(get_db)
) -> None:
    await AuthService(session).forgot_password(body.email)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordRequest, session: AsyncSession = Depends(get_db)
) -> None:
    try:
        await AuthService(session).reset_password(body.email, body.code, body.new_password)
    except InvalidOTPError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


@router.patch("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    try:
        await AuthService(session).change_password(
            user, body.current_password, body.new_password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
