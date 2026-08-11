import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.core.exceptions import (
    FaceMismatchError,
    FaceModelUnavailableError,
    FaceProfileCorruptedError,
    FaceProfileNotFoundError,
    InvalidImageError,
    LivenessCheckFailedError,
    MultipleFacesDetectedError,
    NoFaceDetectedError,
)
from app.core.rate_limit import RateLimiter, get_redis_client
from app.models.user import User
from app.repositories.face_repository import FaceRepository
from app.schemas.face import (
    FaceEnrollOut,
    FaceStatusOut,
    FaceVerificationAttemptListOut,
    FaceVerificationAttemptOut,
    FaceVerifyOut,
)
from app.services.employee_service import EmployeeService
from app.services.face_service import FaceService

router = APIRouter(prefix="/face", tags=["face"])

_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}

_BAD_REQUEST_ERRORS = (InvalidImageError, NoFaceDetectedError, MultipleFacesDetectedError)


async def _face_action_rate_limit(
    user: User = Depends(get_current_user), redis: Redis = Depends(get_redis_client)
) -> None:
    # User-keyed, not IP-keyed — mirrors attendance.py's
    # _attendance_action_rate_limit for the same reason (IP is unreliable for
    # mobile clients, shared-WiFi both under- and over-throttles). Each call
    # here runs a CPU-bound ONNX detect+embed pipeline, same cost profile as
    # the check-in flow that already reuses this pattern.
    settings = get_settings()
    limiter = RateLimiter(
        redis,
        "face-action",
        settings.face_action_rate_limit_per_window,
        settings.face_action_rate_limit_window_seconds,
    )
    await limiter.check(str(user.id))


async def _resolve_employee_id(user: User, session: AsyncSession) -> uuid.UUID:
    employee = await EmployeeService(session).get_by_user_id(user.id)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no employee profile for this account"
        )
    return employee.id


async def _read_and_validate(file: UploadFile, settings: Settings) -> bytes:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported content type: {file.content_type} (expected jpeg or png)",
        )
    content = await file.read()
    max_bytes = settings.face_max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"image exceeds max size of {settings.face_max_upload_size_mb}MB",
        )
    return content


@router.post(
    "/enroll/{employee_id}",
    response_model=FaceEnrollOut,
    dependencies=[
        Depends(require_permission("users:write")),
        Depends(_face_action_rate_limit),
    ],
)
async def enroll(
    employee_id: uuid.UUID,
    photos: list[UploadFile],
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FaceEnrollOut:
    if not (settings.face_enrollment_min_photos <= len(photos) <= settings.face_enrollment_max_photos):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"expected between {settings.face_enrollment_min_photos} and "
                f"{settings.face_enrollment_max_photos} photos, got {len(photos)}"
            ),
        )
    images = [await _read_and_validate(photo, settings) for photo in photos]
    try:
        result = await FaceService(session, settings).enroll(employee_id, images)
    except InvalidImageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FaceModelUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return FaceEnrollOut(
        photos_accepted=result.photos_accepted,
        photos_rejected=result.photos_rejected,
        embedding_dimension=result.embedding_dimension,
    )


@router.post(
    "/verify",
    response_model=FaceVerifyOut,
    dependencies=[Depends(_face_action_rate_limit)],
)
async def verify(
    photo: UploadFile,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FaceVerifyOut:
    employee_id = await _resolve_employee_id(user, session)
    image_bytes = await _read_and_validate(photo, settings)
    try:
        await FaceService(session, settings).verify(employee_id, image_bytes)
    except LivenessCheckFailedError:
        return FaceVerifyOut(verified=False, reason="liveness_failed")
    except FaceMismatchError:
        return FaceVerifyOut(verified=False, reason="low_similarity")
    except FaceProfileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except _BAD_REQUEST_ERRORS as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (FaceModelUnavailableError, FaceProfileCorruptedError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return FaceVerifyOut(verified=True, reason=None)


@router.get("/status", response_model=FaceStatusOut)
async def status_self(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db)
) -> FaceStatusOut:
    employee_id = await _resolve_employee_id(user, session)
    status_dict = await FaceService(session).get_status(employee_id)
    return FaceStatusOut(**status_dict)


@router.get(
    "/status/{employee_id}",
    response_model=FaceStatusOut,
    dependencies=[Depends(require_permission("users:read"))],
)
async def status_for_employee(
    employee_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> FaceStatusOut:
    status_dict = await FaceService(session).get_status(employee_id)
    return FaceStatusOut(**status_dict)


@router.get(
    "/attempts/{employee_id}",
    response_model=FaceVerificationAttemptListOut,
    # Same permission as the geofence-event history view, not users:read —
    # this is the same HR audit-trail feature (2026-08-11 build) and must
    # exclude Supervisor the same way, which users:read does not.
    dependencies=[Depends(require_permission("geofence_events:read"))],
)
async def list_face_attempts(
    employee_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> FaceVerificationAttemptListOut:
    attempts, total = await FaceRepository(session).list_attempts_for_employee(
        employee_id, date_from, date_to, limit, offset
    )
    return FaceVerificationAttemptListOut(
        items=[
            FaceVerificationAttemptOut(
                id=attempt.id,
                passed=attempt.passed,
                failure_reason=attempt.failure_reason.value if attempt.failure_reason else None,
                created_at=attempt.created_at,
            )
            for attempt in attempts
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
