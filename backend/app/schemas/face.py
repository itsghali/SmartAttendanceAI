import uuid
from datetime import datetime

from pydantic import BaseModel


class FaceEnrollRejectedPhoto(BaseModel):
    index: int
    reason: str


class FaceEnrollOut(BaseModel):
    photos_accepted: int
    photos_rejected: list[FaceEnrollRejectedPhoto]
    embedding_dimension: int


class FaceVerifyOut(BaseModel):
    verified: bool
    reason: str | None = None


class FaceStatusOut(BaseModel):
    enrolled: bool
    enrolled_at: datetime | None
    photo_count: int


class FaceVerificationAttemptOut(BaseModel):
    """Deliberately excludes similarity_score/liveness_score — see
    FaceVerificationAttempt's model docstring: those scores are not for
    client consumption, HR included. passed + failure_reason is the
    diagnostic surface HR actually needs ("why did this check-in get
    rejected"), without exposing tunable biometric thresholds."""

    id: uuid.UUID
    passed: bool
    failure_reason: str | None
    created_at: datetime


class FaceVerificationAttemptListOut(BaseModel):
    items: list[FaceVerificationAttemptOut]
    total: int
    limit: int
    offset: int
