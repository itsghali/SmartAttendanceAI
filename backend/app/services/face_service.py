"""Enrollment + verification business logic.

Imports ai/face_recognition in-process (adds the ai/ directory to sys.path,
same prepend_sys_path technique database/migrations/env.py already uses for
cross-package imports) rather than a subprocess or a separate HTTP service —
no new deployment topology, matches the single-monolith setup this repo
already runs.
"""

from __future__ import annotations

import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
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
from app.models.face_verification_attempt import FaceVerificationFailureReason
from app.repositories.face_repository import FaceRepository

_AI_DIR = Path(__file__).resolve().parents[3] / "ai"
if str(_AI_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_DIR))

from face_recognition import pipeline as face_pipeline  # noqa: E402
from face_recognition.exceptions import (  # noqa: E402
    PipelineInvalidImageError,
    PipelineModelUnavailableError,
    PipelineMultiFaceError,
    PipelineNoFaceError,
)

logger = logging.getLogger("app.face")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    # Both vectors are already L2-normalized by the pipeline (ArcFace's
    # normed_embedding, and enroll()'s own averaging renormalizes), so cosine
    # similarity reduces to a plain dot product.
    #
    # Length is asserted, not just trusted: zip() silently stops at the
    # shorter vector, so a live embedding compared against a stale-dimension
    # stored profile (e.g. after a pipeline model swap) would otherwise
    # produce a silently wrong similarity score instead of an error — a real,
    # demonstrated bug, not a hypothetical one. Callers must check dimensions
    # against a domain-appropriate error before reaching this point; this is
    # the last-resort guard.
    if len(a) != len(b):
        raise ValueError(f"embedding dimension mismatch: {len(a)} vs {len(b)}")
    return sum(x * y for x, y in zip(a, b))


@dataclass
class FaceVerifyResult:
    verified: bool
    reason: str | None


@dataclass
class FaceEnrollResult:
    photos_accepted: int
    photos_rejected: list[dict]
    embedding_dimension: int


class FaceService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None):
        self._repo = FaceRepository(session)
        self._settings = settings or get_settings()

    def _check_enabled(self) -> None:
        if not self._settings.face_verification_enabled:
            raise FaceModelUnavailableError("face verification is currently disabled")

    async def enroll(self, employee_id: uuid.UUID, images: list[bytes]) -> FaceEnrollResult:
        self._check_enabled()

        embeddings: list[list[float]] = []
        rejected: list[dict] = []
        for index, image_bytes in enumerate(images):
            try:
                result = face_pipeline.analyze(image_bytes)
            except PipelineInvalidImageError:
                rejected.append({"index": index, "reason": "invalid_image"})
                continue
            except PipelineNoFaceError:
                rejected.append({"index": index, "reason": "no_face"})
                continue
            except PipelineMultiFaceError:
                rejected.append({"index": index, "reason": "multiple_faces"})
                continue
            except PipelineModelUnavailableError as exc:
                raise FaceModelUnavailableError("face model unavailable") from exc
            embeddings.append(result.embedding)

        if not embeddings:
            raise InvalidImageError("no photo produced a usable face embedding")

        dimension = len(embeddings[0])
        averaged = [sum(vec[i] for vec in embeddings) / len(embeddings) for i in range(dimension)]
        norm = sum(v * v for v in averaged) ** 0.5
        normalized = [v / norm for v in averaged] if norm > 0 else averaged

        await self._repo.upsert_profile(
            employee_id=employee_id,
            embedding=normalized,
            model_name=face_pipeline.MODEL_NAME,
            embedding_dimension=dimension,
            enrollment_photo_count=len(embeddings),
        )
        return FaceEnrollResult(
            photos_accepted=len(embeddings),
            photos_rejected=rejected,
            embedding_dimension=dimension,
        )

    async def verify(self, employee_id: uuid.UUID, image_bytes: bytes) -> None:
        """Raises on every outcome, including the two "expected negative"
        cases (FaceMismatchError, LivenessCheckFailedError) — routes/face.py
        catches those two specifically and answers 200 {verified:false,
        reason}, while every other exception here maps to a real HTTP error
        (400/404/503). Keeping them as named exceptions (not a bool return)
        matches this codebase's existing convention and keeps every failure
        mode independently testable and loggable at the point it's decided."""
        self._check_enabled()

        profile = await self._repo.get_profile(employee_id)
        if profile is None:
            await self._repo.record_attempt(
                employee_id, None, None, False, FaceVerificationFailureReason.NOT_ENROLLED
            )
            raise FaceProfileNotFoundError(f"employee {employee_id} has no enrolled face profile")

        try:
            result = face_pipeline.analyze(image_bytes)
        except PipelineInvalidImageError as exc:
            await self._repo.record_attempt(
                employee_id, None, None, False, FaceVerificationFailureReason.INVALID_IMAGE
            )
            raise InvalidImageError(str(exc)) from exc
        except PipelineNoFaceError as exc:
            await self._repo.record_attempt(
                employee_id, None, None, False, FaceVerificationFailureReason.NO_FACE
            )
            raise NoFaceDetectedError(str(exc)) from exc
        except PipelineMultiFaceError as exc:
            await self._repo.record_attempt(
                employee_id, None, None, False, FaceVerificationFailureReason.MULTIPLE_FACES
            )
            raise MultipleFacesDetectedError(str(exc)) from exc
        except PipelineModelUnavailableError as exc:
            raise FaceModelUnavailableError(str(exc)) from exc

        # Liveness gates before similarity — a spoof that also happens to
        # match shouldn't reach the similarity comparison at all.
        logger.debug(
            "liveness=%s threshold=%s", result.liveness, self._settings.face_liveness_threshold
        )
        if result.liveness < self._settings.face_liveness_threshold:
            await self._repo.record_attempt(
                employee_id,
                None,
                result.liveness,
                False,
                FaceVerificationFailureReason.LIVENESS_FAILED,
            )
            raise LivenessCheckFailedError("liveness check failed")

        if len(result.embedding) != profile.embedding_dimension:
            # Profile was enrolled under a different pipeline/model version
            # (mismatched embedding_dimension) — comparing anyway would let
            # _cosine_similarity's zip() silently truncate to a wrong score
            # instead of a real error. Surfaces as "model unavailable" (503,
            # prompts re-enrollment) rather than a false pass/fail.
            await self._repo.record_attempt(
                employee_id,
                None,
                result.liveness,
                False,
                FaceVerificationFailureReason.MODEL_UNAVAILABLE,
            )
            raise FaceModelUnavailableError(
                "enrolled profile is incompatible with the current face model; re-enrollment required"
            )

        try:
            stored_embedding = profile.embedding
        except InvalidToken as exc:
            # No configured decryption key can read this profile's stored
            # embedding — key rotated out, or corrupted data. Distinguished
            # from FaceProfileNotFoundError (see PLAN.md item 5's Eng
            # review) since this employee IS enrolled; the fix is
            # re-enrollment, not treating them as never having enrolled.
            await self._repo.record_attempt(
                employee_id,
                None,
                result.liveness,
                False,
                FaceVerificationFailureReason.PROFILE_CORRUPTED,
            )
            raise FaceProfileCorruptedError(
                "enrolled profile could not be read; re-enrollment required"
            ) from exc

        similarity = _cosine_similarity(result.embedding, stored_embedding)
        passed = similarity >= self._settings.face_similarity_threshold
        await self._repo.record_attempt(
            employee_id,
            similarity,
            result.liveness,
            passed,
            None if passed else FaceVerificationFailureReason.LOW_SIMILARITY,
        )
        if not passed:
            raise FaceMismatchError("face did not match enrolled profile")

    async def get_status(self, employee_id: uuid.UUID) -> dict:
        profile = await self._repo.get_profile(employee_id)
        if profile is None:
            return {"enrolled": False, "enrolled_at": None, "photo_count": 0}
        return {
            "enrolled": True,
            "enrolled_at": profile.created_at,
            "photo_count": profile.enrollment_photo_count,
        }
