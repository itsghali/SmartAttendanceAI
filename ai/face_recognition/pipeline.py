"""Face detection + ArcFace embedding + passive liveness scoring.

Model stack: insightface's buffalo_l pack (RetinaFace detection/alignment +
ArcFace recognition), ONNX-backed via onnxruntime — no torch dependency.
Models are fetched to ~/.insightface/models on first use; the first call in
a fresh environment will be slow (network fetch + model load). Loaded once
as a module-level singleton and reused across calls.

SUPPLY-CHAIN TRUST ASSUMPTION, documented not silently accepted: the buffalo_l
weights are fetched from insightface's own model-zoo hosting by the
`insightface` package's internal downloader, with no checksum verification in
this codebase and no vendored/mirrored copy. This is the same class of
exposure as the liveness-model gap below — an unverified binary feeding
biometric matching decisions — except this one is already running in the
shipped enrollment/verification path, not a hypothetical future swap. A
plausible-looking SHA256 for buffalo_l.zip surfaces in third-party mirror
listings, but nothing found so far traces to an authoritative source insightface
itself publishes (e.g. a checksums manifest in their GitHub releases) — hardcoding
an unverified hash here would be worse than no pinning (false confidence), so
this is deliberately left undone rather than guessed. Before trusting this in
production: either vendor a specific model version with an operator-verified
checksum, or confirm an authoritative published hash to pin against.

Liveness is a passive, single-frame heuristic (blur/sharpness + moire/
frequency-domain analysis), not a trained anti-spoof classifier. A vetted
pretrained anti-spoof ONNX model would be a strictly better drop-in
replacement for `liveness_score()` — deferred rather than shipping an
unverified downloaded binary of uncertain license/provenance. Documented
limitation, not a silent gap.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from face_recognition.exceptions import (
    PipelineInvalidImageError,
    PipelineModelUnavailableError,
    PipelineMultiFaceError,
    PipelineNoFaceError,
)

MODEL_NAME = "insightface_buffalo_l"
EMBEDDING_DIMENSION = 512

# A rate limiter on the caller (routes/face.py) caps request *volume* during
# a model-outage window, but without this, every rejected request still pays
# the full FaceAnalysis(...) + .prepare() construction cost before failing —
# a corrupted/missing model plus N concurrent users each retrying within
# their rate-limit budget is still a thundering-herd CPU spike. Caching the
# failure for a short window turns each retry into an immediate, cheap
# rejection instead.
_LOAD_FAILURE_BACKOFF_SECONDS = 30.0

_app = None
_load_failed_at: float | None = None
_app_lock = threading.Lock()


def _get_app():
    global _app, _load_failed_at
    if _app is not None:
        return _app
    with _app_lock:
        if _app is not None:
            return _app
        if _load_failed_at is not None:
            elapsed = time.monotonic() - _load_failed_at
            if elapsed < _LOAD_FAILURE_BACKOFF_SECONDS:
                raise PipelineModelUnavailableError(
                    f"face model failed to load {elapsed:.0f}s ago; not retrying yet"
                )
        try:
            from insightface.app import FaceAnalysis

            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=-1, det_size=(640, 640))
        except Exception as exc:  # model missing/corrupt/onnxruntime init failure
            _load_failed_at = time.monotonic()
            raise PipelineModelUnavailableError(
                "face model failed to load"
            ) from exc
        _app = app
        _load_failed_at = None
    return _app


def warm_up() -> None:
    """Force model load at startup so the first real request isn't the one
    that pays for it. Safe to call multiple times (idempotent)."""
    _get_app()


def decode_image(image_bytes: bytes) -> np.ndarray:
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise PipelineInvalidImageError("could not decode image")
    return image


def _detect_single_face(image_bgr: np.ndarray):
    app = _get_app()
    try:
        faces = app.get(image_bgr)
    except Exception as exc:
        raise PipelineModelUnavailableError("face model inference failed") from exc

    if len(faces) == 0:
        raise PipelineNoFaceError("no face detected in image")
    if len(faces) > 1:
        raise PipelineMultiFaceError(f"{len(faces)} faces detected, expected exactly 1")
    return faces[0]


def embed(face) -> list[float]:
    return face.normed_embedding.tolist()


def _laplacian_sharpness(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _moire_energy_ratio(gray: np.ndarray) -> float:
    """Ratio of energy in a mid-high frequency band of the 2D FFT magnitude
    spectrum. Screen replays commonly show periodic pixel-grid artifacts
    (moire) that concentrate energy in this band more than a genuine camera
    capture of a real face does."""
    f = np.fft.fft2(gray.astype(np.float32))
    magnitude = np.abs(np.fft.fftshift(f))
    h, w = magnitude.shape
    cy, cx = h // 2, w // 2
    y, x = np.ogrid[:h, :w]
    radius = np.sqrt((y - cy) ** 2 + (x - cx) ** 2)
    max_radius = min(cy, cx)
    if max_radius == 0:
        return 0.0
    band = (radius > 0.35 * max_radius) & (radius < 0.75 * max_radius)
    total_energy = magnitude.sum()
    if total_energy == 0:
        return 0.0
    return float(magnitude[band].sum() / total_energy)


def liveness_score(image_bgr: np.ndarray, face) -> float:
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    x1, y1 = max(x1, 0), max(y1, 0)
    crop = image_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    sharpness = _laplacian_sharpness(gray)
    # Empirically low-detail thresholds vary a lot by camera; normalize with a
    # soft cap rather than a hard cutoff so a slightly-blurry real photo isn't
    # zeroed out. Tune during pilot alongside the similarity threshold.
    sharpness_score = min(sharpness / 150.0, 1.0)

    moire_ratio = _moire_energy_ratio(gray)
    # Higher moire energy = more spoof-like, so invert.
    moire_score = max(0.0, 1.0 - moire_ratio * 4.0)

    return round(0.5 * sharpness_score + 0.5 * moire_score, 4)


@dataclass
class FaceAnalysisResult:
    embedding: list[float]
    liveness: float


def analyze(image_bytes: bytes) -> FaceAnalysisResult:
    """Full pipeline for one uploaded image: decode -> detect exactly one
    face -> embed + liveness score. Raises PipelineInvalidImageError /
    PipelineNoFaceError / PipelineMultiFaceError / PipelineModelUnavailableError."""
    image_bgr = decode_image(image_bytes)
    face = _detect_single_face(image_bgr)
    return FaceAnalysisResult(
        embedding=embed(face),
        liveness=liveness_score(image_bgr, face),
    )
