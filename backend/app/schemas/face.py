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
