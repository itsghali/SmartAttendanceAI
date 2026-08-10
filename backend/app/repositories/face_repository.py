import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.face_profile import FaceProfile
from app.models.face_verification_attempt import (
    FaceVerificationAttempt,
    FaceVerificationFailureReason,
)


class FaceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_profile(self, employee_id: uuid.UUID) -> FaceProfile | None:
        stmt = select(FaceProfile).where(FaceProfile.employee_id == employee_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def upsert_profile(
        self,
        employee_id: uuid.UUID,
        embedding: list[float],
        model_name: str,
        embedding_dimension: int,
        enrollment_photo_count: int,
    ) -> FaceProfile:
        profile = await self.get_profile(employee_id)
        if profile is None:
            profile = FaceProfile(employee_id=employee_id)
            self._session.add(profile)
        profile.embedding = embedding
        profile.model_name = model_name
        profile.embedding_dimension = embedding_dimension
        profile.enrollment_photo_count = enrollment_photo_count
        await self._session.flush()
        return profile

    async def record_attempt(
        self,
        employee_id: uuid.UUID,
        similarity_score: float | None,
        liveness_score: float | None,
        passed: bool,
        failure_reason: FaceVerificationFailureReason | None,
    ) -> FaceVerificationAttempt:
        attempt = FaceVerificationAttempt(
            employee_id=employee_id,
            similarity_score=similarity_score,
            liveness_score=liveness_score,
            passed=passed,
            failure_reason=failure_reason,
        )
        self._session.add(attempt)
        await self._session.flush()
        return attempt
