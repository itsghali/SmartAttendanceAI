import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
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
        await self._session.commit()
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
        await self._session.commit()
        return attempt

    async def list_attempts_for_employee(
        self,
        employee_id: uuid.UUID,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[FaceVerificationAttempt], int]:
        """Same event-grain reasoning as GeofenceEventRepository.list_for_employee
        — this is its own query, not a reuse of a session/attendance-grained
        method, and it never selects similarity_score/liveness_score into the
        response layer (see the model's own docstring: those scores are not
        for client consumption, HR included)."""
        stmt = select(FaceVerificationAttempt).where(
            FaceVerificationAttempt.employee_id == employee_id
        )
        count_stmt = (
            select(func.count())
            .select_from(FaceVerificationAttempt)
            .where(FaceVerificationAttempt.employee_id == employee_id)
        )

        if date_from is not None:
            start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
            stmt = stmt.where(FaceVerificationAttempt.created_at >= start)
            count_stmt = count_stmt.where(FaceVerificationAttempt.created_at >= start)
        if date_to is not None:
            end = datetime.combine(date_to, time.min, tzinfo=timezone.utc) + timedelta(days=1)
            stmt = stmt.where(FaceVerificationAttempt.created_at < end)
            count_stmt = count_stmt.where(FaceVerificationAttempt.created_at < end)

        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(FaceVerificationAttempt.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total
