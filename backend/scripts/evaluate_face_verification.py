"""Independent evaluation of the pretrained InsightFace verification pipeline
SmartAttendanceAI already runs in production, against the public LFW dataset.

THIS IS AN EVALUATION, NOT TRAINING. No model weights are modified, fitted,
or fine-tuned anywhere in this script. `insightface.app.FaceAnalysis` is used
exactly as `ai/face_recognition/pipeline.py` already uses it in production
(same model pack, same provider, same det_size) via `face_pipeline.analyze()`
-- the exact production entry point, called the same way
`backend/app/services/face_service.py` calls it, and the exact same way
`backend/scripts/smoke_test_face.py` (an existing precedent in this repo)
already imports it: sys.path-injecting ai/ rather than a subprocess.

Evaluated pipeline (verified from ai/face_recognition/pipeline.py, not
assumed): InsightFace Buffalo_L -> SCRFD face detector (det_10g.onnx) ->
InsightFace's own internal 5-point landmark alignment/normalization ->
ArcFace ResNet-50 embedding (w600k_r50.onnx) -> 512-d L2-normalized
embedding -> cosine similarity -> threshold. NOTE: pipeline.py's own
module docstring calls the detector "RetinaFace" loosely -- that is the
repository's imprecise shorthand, not this evaluation's terminology. The
actual detector in the buffalo_l pack is SCRFD (InsightFace's
RetinaFace-lineage successor). This discrepancy is deliberately reported,
not silently corrected without mention.

Scope: 1:1, pair-based face VERIFICATION only (not 1:N identification, not
template-based). Liveness (a separate, orthogonal heuristic gate in
pipeline.py that runs BEFORE similarity in production) is explicitly OUT OF
SCOPE here -- this script evaluates only the
detection -> embedding -> similarity -> threshold path, matching the
pipeline diagram the evaluation was scoped against.

The only duplicated production logic in this file is `_cosine_similarity`
(re-implemented locally to avoid importing the full FastAPI/SQLAlchemy/
Settings import graph of backend/app/services/face_service.py into this
script's hot loop). Its exact equivalence to production's
`app.services.face_service._cosine_similarity` is proven by
test_evaluate_face_verification.py::test_cosine_similarity_matches_production,
which imports the real production function directly and asserts bit-identical
output on fixed vectors -- run that test before trusting this script's
results.

Dataset: LFW (Labeled Faces in the Wild), deep-funneled, downloaded from
https://ndownloader.figshare.com/files/5976015 -- the same mirror
scikit-learn's own `fetch_lfw_people`/`fetch_lfw_pairs` fetchers use
internally. LFW's official host (vis-www.cs.umass.edu) does not resolve from
this environment; this mirror was confirmed reachable and confirmed (via
Content-Disposition header) to serve `lfw-funneled.tgz` before this script
was written.

LICENSE: the official LFW usage-terms page could not be reached from this
environment (DNS resolution failure, confirmed via both direct HTTP and
WebFetch), and the HuggingFace mirror of this dataset (logasja/lfw)
explicitly declares "License: [More Information Needed]" in its own
metadata. Per this evaluation's own academic-rigor requirement: license/
usage terms COULD NOT BE INDEPENDENTLY VERIFIED from an authoritative
source. This is reported verbatim in results.json and report_section.md,
not guessed or assumed.

GPU_MODE (see config below): when True, this is an EXPLICIT, USER-DIRECTED deviation
from production fidelity -- production (ai/face_recognition/pipeline.py) is hard-coded
CPU-only (CPUExecutionProvider, ctx_id=-1) and is never modified by this script; GPU_MODE
instead pre-seeds the same production analyze() pipeline's model singleton with a
CUDAExecutionProvider-backed FaceAnalysis instance for speed. Every output says so
explicitly (see get_environment_info/generate_report_section) -- results run under
GPU_MODE=True do NOT represent production's actual deployed configuration.

Reproduction:
    cd backend
    .venv/Scripts/python.exe -m pytest scripts/test_evaluate_face_verification.py -v
    .venv/Scripts/python.exe scripts/evaluate_face_verification.py

Failure policy: any of dataset-download failure, model-load failure,
insufficient valid images after filtering, pair-generation failure, or a
metric-computation error raises immediately and HALTS -- no partial or
fabricated results.json/report_section.md is ever written. See
`EvaluationFailure`.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import random
import sys
import tarfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# sys.path injection -- identical convention to backend/scripts/smoke_test_face.py
# and backend/app/services/face_service.py: put ai/ on sys.path and import the
# production pipeline module directly, in-process, no subprocess.
# ---------------------------------------------------------------------------
_AI_DIR = Path(__file__).resolve().parents[2] / "ai"
if str(_AI_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_DIR))

from face_recognition import pipeline as face_pipeline  # noqa: E402
from face_recognition.exceptions import (  # noqa: E402
    PipelineInvalidImageError,
    PipelineModelUnavailableError,
    PipelineMultiFaceError,
    PipelineNoFaceError,
)

# ---------------------------------------------------------------------------
# Config -- every knob that affects reproducibility lives here.
# ---------------------------------------------------------------------------
SEED = 42
MIN_IMAGES_PER_PERSON = 4
# Images sampled per qualifying identity. Fixed at MIN_IMAGES_PER_PERSON
# (matches the task's own "Person A: A1 A2 A3 A4" example structure) so every
# identity contributes the same, bounded number of genuine pairs
# (C(4,2)=6) regardless of how many images that identity happens to have in
# raw LFW (a handful of celebrities have several hundred) -- a pairing-
# BALANCE decision, distinct from (and not a limit on) which identities are
# included.
IMAGES_PER_IDENTITY = MIN_IMAGES_PER_PERSON
# No identity cap by default -- use every eligible identity. Only overridden
# if the measured pilot timing projects a full run exceeding
# MAX_RUNTIME_MINUTES; if that happens, the cap, the reason, and the
# eligible-vs-selected counts are all reported explicitly (see
# select_identities_and_images / PilotResult).
MAX_IDENTITIES: int | None = None
MAX_RUNTIME_MINUTES = 90.0
PILOT_IMAGE_COUNT = 20
PRODUCTION_THRESHOLD = 0.6
TARGET_FAR = 0.01
BOOTSTRAP_ITERATIONS = 2000
BOOTSTRAP_CI_PERCENTILES = (2.5, 97.5)
COARSE_GRID_POINTS = 41  # visualization only, never used for a reported metric

# ---------------------------------------------------------------------------
# GPU deviation -- EXPLICIT, USER-DIRECTED, NOT the default. Production
# (ai/face_recognition/pipeline.py) hard-codes CPUExecutionProvider/ctx_id=-1
# and is NEVER modified by this script. When GPU_MODE is True, this script
# instead pre-seeds pipeline.py's `_app` module-level singleton with a
# FaceAnalysis instance built with CUDAExecutionProvider, so `analyze()`'s
# own decode/detect/embed/liveness LOGIC (production code, byte-identical)
# runs against a different ONNX execution backend -- not a second
# face-recognition implementation, just a different provider for the same
# calls. This was an explicit tradeoff requested by the user after being
# told it breaks the "exact production pipeline" fidelity claim: production
# is CPU-only, so a GPU run is evaluating a DIFFERENT configuration than
# what's deployed. Every output (results.json, report_section.md) says so
# plainly -- see get_environment_info() and generate_report_section().
# ---------------------------------------------------------------------------
GPU_MODE = True
GPU_DEVICE_ID = 0

LFW_URL = "https://ndownloader.figshare.com/files/5976015"
LFW_EXPECTED_FILENAME = "lfw-funneled.tgz"

_REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = _REPO_ROOT / "backend" / ".face_eval_cache"
ARCHIVE_PATH = CACHE_DIR / LFW_EXPECTED_FILENAME
EXTRACT_DIR = CACHE_DIR / "extracted"
RESULTS_DIR = Path(__file__).resolve().parent / "face_eval_results"

LICENSE_VERIFICATION_NOTE = (
    "License/usage terms could not be independently verified. Attempted: (1) direct HTTP "
    "request to the official LFW host vis-www.cs.umass.edu -- DNS resolution failed from "
    "this environment; (2) WebFetch of the same URL -- same DNS failure; (3) WebFetch of an "
    "archive.org snapshot -- tool could not fetch web.archive.org; (4) the HuggingFace mirror "
    "dataset card (huggingface.co/datasets/logasja/lfw) and its API metadata -- both "
    "explicitly report 'License: [More Information Needed]', not a usable license statement. "
    "No authoritative license text was obtained. This dataset is downloaded here via the "
    "figshare mirror scikit-learn's own LFW fetchers use "
    "(https://ndownloader.figshare.com/files/5976015), which is a data-hosting mirror, not a "
    "license authority."
)


class EvaluationFailure(RuntimeError):
    """Raised on any unrecoverable failure. Caught only at the top of main() to
    print a clear diagnostic and exit non-zero -- never to produce partial or
    fabricated results."""


# ---------------------------------------------------------------------------
# Cosine similarity -- the ONE piece of production logic re-implemented here
# (see module docstring for why, and test_evaluate_face_verification.py for
# the equivalence proof against the real
# app.services.face_service._cosine_similarity).
# ---------------------------------------------------------------------------
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"embedding dimension mismatch: {len(a)} vs {len(b)}")
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Dataset acquisition
# ---------------------------------------------------------------------------
def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def configure_gpu_execution() -> dict:
    """Pre-seeds face_recognition.pipeline's module-level `_app` singleton
    with a FaceAnalysis instance built with CUDAExecutionProvider, so every
    subsequent face_pipeline.analyze() call (unmodified production code)
    runs its detection+embedding on GPU instead of production's CPU-only
    configuration. Returns the actual provider list the loaded ONNX sessions
    report using, for honest recording in results.json (never assumed)."""
    from insightface.app import FaceAnalysis

    print(f"GPU_MODE enabled -- loading buffalo_l with CUDAExecutionProvider (device {GPU_DEVICE_ID})...")
    app = FaceAnalysis(name="buffalo_l", providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    app.prepare(ctx_id=GPU_DEVICE_ID, det_size=(640, 640))
    face_pipeline._app = app  # noqa: SLF001 -- deliberate singleton pre-seed, see module docstring

    actual_providers: dict[str, list[str]] = {}
    for model_name, model in app.models.items():
        session = getattr(model, "session", None)
        if session is not None:
            actual_providers[model_name] = session.get_providers()
    return actual_providers


def download_dataset() -> tuple[Path, str, str]:
    """Downloads (if not already cached) and extracts LFW. Returns
    (extract_root, archive_sha256, retrieved_at_iso). Raises EvaluationFailure
    on any download/extraction problem -- never proceeds on a partial archive."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()

    if not ARCHIVE_PATH.exists():
        print(f"Downloading LFW from {LFW_URL} ...")
        try:
            tmp_path = ARCHIVE_PATH.with_suffix(".partial")
            with urllib.request.urlopen(LFW_URL, timeout=60) as resp, open(tmp_path, "wb") as out:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 1 << 20
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = 100 * downloaded / total
                        print(f"\r  {downloaded / 1e6:.1f}MB / {total / 1e6:.1f}MB ({pct:.1f}%)", end="")
                print()
            tmp_path.rename(ARCHIVE_PATH)
        except Exception as exc:
            raise EvaluationFailure(f"LFW dataset download failed: {exc}") from exc
    else:
        print(f"Using cached archive at {ARCHIVE_PATH}")

    if not ARCHIVE_PATH.exists() or ARCHIVE_PATH.stat().st_size == 0:
        raise EvaluationFailure("LFW archive missing or empty after download attempt")

    archive_sha256 = _sha256_file(ARCHIVE_PATH)
    print(f"Archive SHA-256: {archive_sha256}")

    if not EXTRACT_DIR.exists() or not any(EXTRACT_DIR.iterdir()):
        print(f"Extracting to {EXTRACT_DIR} ...")
        EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(ARCHIVE_PATH, "r:gz") as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(EXTRACT_DIR, filter="data")
                else:  # pragma: no cover - older Python without extraction filters
                    tar.extractall(EXTRACT_DIR)
        except Exception as exc:
            raise EvaluationFailure(f"LFW archive extraction failed: {exc}") from exc
    else:
        print(f"Using cached extraction at {EXTRACT_DIR}")

    # LFW's deep-funneled archive extracts to a single top-level directory
    # containing one subdirectory per identity. Detect it rather than assume
    # a fixed name, since mirrors sometimes rename the top-level folder.
    candidates = [p for p in EXTRACT_DIR.iterdir() if p.is_dir()]
    root = candidates[0] if len(candidates) == 1 else EXTRACT_DIR
    person_dirs = [p for p in root.iterdir() if p.is_dir()]
    if not person_dirs:
        raise EvaluationFailure(
            f"extraction produced no identity subdirectories under {root} -- archive layout "
            "unexpected, cannot proceed"
        )
    return root, archive_sha256, retrieved_at


def load_identities(root: Path) -> dict[str, list[Path]]:
    identities: dict[str, list[Path]] = {}
    for person_dir in sorted(root.iterdir()):
        if not person_dir.is_dir():
            continue
        images = sorted(
            p for p in person_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")
        )
        if images:
            identities[person_dir.name] = images
    if not identities:
        raise EvaluationFailure(f"no identities with images found under {root}")
    return identities


@dataclass
class DatasetWideStats:
    total_identities: int
    total_images: int
    identities_with_2plus_images: int
    identities_with_min_images: int  # >= MIN_IMAGES_PER_PERSON
    images_in_identities_with_min_images: int

    def to_dict(self) -> dict:
        return dict(vars(self))


def compute_dataset_wide_stats(identities: dict[str, list[Path]]) -> DatasetWideStats:
    total_images = sum(len(v) for v in identities.values())
    with_2plus = sum(1 for v in identities.values() if len(v) >= 2)
    eligible = {k: v for k, v in identities.items() if len(v) >= MIN_IMAGES_PER_PERSON}
    return DatasetWideStats(
        total_identities=len(identities),
        total_images=total_images,
        identities_with_2plus_images=with_2plus,
        identities_with_min_images=len(eligible),
        images_in_identities_with_min_images=sum(len(v) for v in eligible.values()),
    )


# ---------------------------------------------------------------------------
# Pilot timing + scale decision (requirement #1: no arbitrary small cap)
# ---------------------------------------------------------------------------
@dataclass
class PilotResult:
    images_timed: int
    mean_seconds_per_image: float
    total_eligible_identities: int
    total_eligible_images: int
    projected_full_runtime_minutes: float
    max_runtime_minutes: float
    cap_applied: bool
    cap_reason: str | None
    selected_identities: int
    selected_images: int

    def to_dict(self) -> dict:
        return dict(vars(self))


def run_pilot_and_decide_scale(
    eligible: dict[str, list[Path]], max_runtime_minutes: float, max_identities_override: int | None
) -> PilotResult:
    pilot_images: list[Path] = []
    for images in eligible.values():
        pilot_images.extend(images[:1])
        if len(pilot_images) >= PILOT_IMAGE_COUNT:
            break
    pilot_images = pilot_images[:PILOT_IMAGE_COUNT]

    print(f"Timing pilot batch of {len(pilot_images)} images...")
    start = time.monotonic()
    timed = 0
    for path in pilot_images:
        try:
            face_pipeline.analyze(path.read_bytes())
        except Exception:
            pass  # pilot only measures latency, detection outcome irrelevant here
        timed += 1
    elapsed = time.monotonic() - start
    mean_seconds = elapsed / max(timed, 1)
    print(f"  mean latency: {mean_seconds:.3f}s/image over {timed} images")

    total_eligible_images = sum(len(v) for v in eligible.values())
    total_eligible_identities = len(eligible)
    # Every eligible identity contributes IMAGES_PER_IDENTITY images to the
    # actual run (not its full raw count) -- project runtime on THAT figure,
    # since that's what will actually be embedded.
    images_that_will_be_processed = total_eligible_identities * IMAGES_PER_IDENTITY
    projected_minutes = images_that_will_be_processed * mean_seconds / 60.0

    cap_applied = False
    cap_reason = None
    selected_identity_count = total_eligible_identities

    if max_identities_override is not None:
        cap_applied = True
        cap_reason = f"MAX_IDENTITIES explicitly set to {max_identities_override} in script config"
        selected_identity_count = min(max_identities_override, total_eligible_identities)
    elif projected_minutes > max_runtime_minutes:
        cap_applied = True
        # Solve for the identity count that fits the runtime budget.
        budget_seconds = max_runtime_minutes * 60.0
        seconds_per_identity = IMAGES_PER_IDENTITY * mean_seconds
        selected_identity_count = max(1, int(budget_seconds / seconds_per_identity))
        selected_identity_count = min(selected_identity_count, total_eligible_identities)
        cap_reason = (
            f"measured pilot latency ({mean_seconds:.3f}s/image over {timed} images) projects "
            f"a full run over all {total_eligible_identities} eligible identities "
            f"({images_that_will_be_processed} images to embed) at "
            f"{projected_minutes:.1f} minutes, exceeding the configured "
            f"MAX_RUNTIME_MINUTES={max_runtime_minutes}. Capped to "
            f"{selected_identity_count} identities to fit the runtime budget."
        )

    return PilotResult(
        images_timed=timed,
        mean_seconds_per_image=mean_seconds,
        total_eligible_identities=total_eligible_identities,
        total_eligible_images=total_eligible_images,
        projected_full_runtime_minutes=projected_minutes,
        max_runtime_minutes=max_runtime_minutes,
        cap_applied=cap_applied,
        cap_reason=cap_reason,
        selected_identities=selected_identity_count,
        selected_images=selected_identity_count * IMAGES_PER_IDENTITY,
    )


def select_identities_and_images(
    eligible: dict[str, list[Path]], identity_count: int, images_per_identity: int, seed: int
) -> dict[str, list[Path]]:
    rng = random.Random(seed)
    identity_names = sorted(eligible.keys())
    if identity_count < len(identity_names):
        identity_names = rng.sample(identity_names, k=identity_count)
        identity_names.sort()
    selected: dict[str, list[Path]] = {}
    for name in identity_names:
        images = eligible[name]
        chosen = rng.sample(images, k=images_per_identity) if len(images) > images_per_identity else list(images)
        chosen.sort()
        selected[name] = chosen
    return selected


# ---------------------------------------------------------------------------
# Pair generation -- 1:1 verification pairs, no self-pairs, no reversed
# duplicates. Documented explicitly per requirement #6.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Pair:
    identity_a: str
    identity_b: str
    image_a: Path
    image_b: Path
    label: int  # 1 = genuine (same identity), 0 = impostor


def generate_genuine_pairs(selected: dict[str, list[Path]]) -> list[Pair]:
    pairs: list[Pair] = []
    for identity, images in selected.items():
        for i in range(len(images)):
            for j in range(i + 1, len(images)):  # i < j: no self-pair, no reversed duplicate
                pairs.append(Pair(identity, identity, images[i], images[j], 1))
    return pairs


def generate_impostor_pairs(selected: dict[str, list[Path]], target_count: int, seed: int) -> list[Pair]:
    rng = random.Random(seed)
    identities = list(selected.keys())
    seen: set[tuple[str, str]] = set()
    pairs: list[Pair] = []
    max_attempts = target_count * 50 + 1000
    attempts = 0
    while len(pairs) < target_count and attempts < max_attempts:
        attempts += 1
        id_a, id_b = rng.sample(identities, 2)
        img_a = rng.choice(selected[id_a])
        img_b = rng.choice(selected[id_b])
        key = tuple(sorted((f"{id_a}::{img_a.name}", f"{id_b}::{img_b.name}")))
        if key in seen:
            continue
        seen.add(key)
        pairs.append(Pair(id_a, id_b, img_a, img_b, 0))
    return pairs


# ---------------------------------------------------------------------------
# Pipeline invocation -- calls the real production analyze() on every unique
# image exactly once; results cached and reused across all pairs referencing
# that image.
# ---------------------------------------------------------------------------
@dataclass
class ImageOutcome:
    path: Path
    identity: str
    status: str  # "success" | "invalid_image" | "no_face" | "multiple_faces" | "model_unavailable"
    embedding: list[float] | None = None


def embed_all_images(selected: dict[str, list[Path]]) -> dict[Path, ImageOutcome]:
    outcomes: dict[Path, ImageOutcome] = {}
    total = sum(len(v) for v in selected.values())
    done = 0
    for identity, images in selected.items():
        for path in images:
            done += 1
            if done % 50 == 0 or done == total:
                print(f"\rEmbedding images: {done}/{total}", end="")
            try:
                result = face_pipeline.analyze(path.read_bytes())
                outcomes[path] = ImageOutcome(path, identity, "success", result.embedding)
            except PipelineInvalidImageError:
                outcomes[path] = ImageOutcome(path, identity, "invalid_image")
            except PipelineNoFaceError:
                outcomes[path] = ImageOutcome(path, identity, "no_face")
            except PipelineMultiFaceError:
                outcomes[path] = ImageOutcome(path, identity, "multiple_faces")
            except PipelineModelUnavailableError as exc:
                raise EvaluationFailure(f"InsightFace model unavailable during embedding: {exc}") from exc
    print()
    return outcomes


def summarize_image_processing(outcomes: dict[Path, ImageOutcome]) -> dict:
    total = len(outcomes)
    by_status: dict[str, int] = {}
    for o in outcomes.values():
        by_status[o.status] = by_status.get(o.status, 0) + 1
    successful = by_status.get("success", 0)
    return {
        "total_images": total,
        "successful_embeddings": successful,
        "failed_images": total - successful,
        "success_rate": successful / total if total else None,
        "failure_rate": (total - successful) / total if total else None,
        "failure_reason_counts": {k: v for k, v in by_status.items() if k != "success"},
    }


# ---------------------------------------------------------------------------
# Pair scoring
# ---------------------------------------------------------------------------
@dataclass
class ScoredPair:
    identity_a: str
    identity_b: str
    image_a: Path
    image_b: Path
    label: int
    similarity: float


def score_pairs(pairs: list[Pair], outcomes: dict[Path, ImageOutcome]) -> tuple[list[ScoredPair], list[Pair]]:
    scored: list[ScoredPair] = []
    unusable: list[Pair] = []
    for p in pairs:
        oa, ob = outcomes.get(p.image_a), outcomes.get(p.image_b)
        if oa is None or ob is None or oa.status != "success" or ob.status != "success":
            unusable.append(p)
            continue
        sim = _cosine_similarity(oa.embedding, ob.embedding)
        scored.append(ScoredPair(p.identity_a, p.identity_b, p.image_a, p.image_b, p.label, sim))
    return scored, unusable


# ---------------------------------------------------------------------------
# Threshold metrics -- full score-derived sweep is the primary evaluation
# (requirement #2/#16), computed with the exact production comparison
# `similarity >= threshold`.
# ---------------------------------------------------------------------------
@dataclass
class ThresholdMetrics:
    threshold: float
    tp: int
    tn: int
    fp: int
    fn: int
    accuracy: float
    precision: float | None
    recall: float | None
    f1: float | None
    far: float | None
    frr: float | None
    specificity: float | None

    def to_dict(self) -> dict:
        return dict(vars(self))


def evaluate_at_threshold(scores: np.ndarray, labels: np.ndarray, threshold: float) -> ThresholdMetrics:
    predicted = scores >= threshold  # exact production comparison, never nearest-grid
    genuine = labels == 1
    impostor = labels == 0
    tp = int(np.sum(predicted & genuine))
    fn = int(np.sum(~predicted & genuine))
    fp = int(np.sum(predicted & impostor))
    tn = int(np.sum(~predicted & impostor))
    total = tp + tn + fp + fn
    accuracy = (tp + tn) / total if total else float("nan")
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall) > 0) else None
    far = fp / (fp + tn) if (fp + tn) else None
    frr = fn / (fn + tp) if (fn + tp) else None
    specificity = tn / (tn + fp) if (tn + fp) else None
    return ThresholdMetrics(threshold, tp, tn, fp, fn, accuracy, precision, recall, f1, far, frr, specificity)


def full_threshold_sweep(scores: np.ndarray, labels: np.ndarray) -> list[ThresholdMetrics]:
    """Exhaustive, score-derived threshold set -- every unique observed
    similarity score, plus one point above the maximum (rejects everything)
    -- the complete set of distinct decision boundaries. This is the
    PRIMARY threshold evaluation (requirement #2); the 41-point grid is used
    only for plotting (see coarse_threshold_grid)."""
    unique_scores = np.unique(scores)
    thresholds = np.concatenate([unique_scores, [unique_scores[-1] + 1e-9]])
    return [evaluate_at_threshold(scores, labels, float(t)) for t in thresholds]


def coarse_threshold_grid(scores: np.ndarray, labels: np.ndarray, n: int = COARSE_GRID_POINTS) -> list[ThresholdMetrics]:
    grid = np.linspace(float(scores.min()), float(scores.max()), n)
    return [evaluate_at_threshold(scores, labels, float(t)) for t in grid]


def find_max_f1(sweep: list[ThresholdMetrics]) -> ThresholdMetrics:
    scored = [m for m in sweep if m.f1 is not None]
    if not scored:
        raise EvaluationFailure("no threshold in the sweep has a defined F1 score")
    return max(scored, key=lambda m: m.f1)


def find_target_far_threshold(sweep: list[ThresholdMetrics], target_far: float) -> ThresholdMetrics | None:
    candidates = [m for m in sweep if m.far is not None and m.far <= target_far]
    if not candidates:
        return None
    # Among thresholds meeting the FAR constraint, the LOWEST threshold gives
    # the best (lowest) FRR while still satisfying FAR <= target.
    return min(candidates, key=lambda m: m.threshold)


# ---------------------------------------------------------------------------
# EER -- interpolated from the full score-derived sweep's own (FAR, FRR)
# sequence, not the coarse visualization grid. See module docstring / plan
# for why this is self-consistent with the primary threshold table rather
# than relying on sklearn.roc_curve's separate threshold convention.
# ---------------------------------------------------------------------------
@dataclass
class EerResult:
    eer: float
    threshold: float
    far_at_eer: float
    frr_at_eer: float
    method: str

    def to_dict(self) -> dict:
        return dict(vars(self))


def interpolated_eer(sweep: list[ThresholdMetrics]) -> EerResult:
    """sweep must be sorted by ascending threshold (full_threshold_sweep's
    output already is, since it's built from np.unique's sorted output).
    FAR decreases monotonically as threshold increases; FRR increases
    monotonically. Finds the threshold where they cross via linear
    interpolation between the two bracketing points."""
    usable = [m for m in sweep if m.far is not None and m.frr is not None]
    if len(usable) < 2:
        raise EvaluationFailure("threshold sweep has too few usable points to estimate EER")

    diffs = [m.far - m.frr for m in usable]  # positive when FAR>FRR (loose threshold), negative when strict
    for i in range(len(usable) - 1):
        d0, d1 = diffs[i], diffs[i + 1]
        if d0 == 0:
            m = usable[i]
            return EerResult((m.far + m.frr) / 2, m.threshold, m.far, m.frr, "exact_zero_crossing")
        if (d0 > 0 and d1 < 0) or (d0 < 0 and d1 > 0):
            m0, m1 = usable[i], usable[i + 1]
            # Linear interpolation for the threshold where diff == 0.
            frac = d0 / (d0 - d1)
            threshold = m0.threshold + frac * (m1.threshold - m0.threshold)
            far = m0.far + frac * (m1.far - m0.far)
            frr = m0.frr + frac * (m1.frr - m0.frr)
            eer = (far + frr) / 2
            return EerResult(eer, threshold, far, frr, "linear_interpolation_between_bracketing_thresholds")

    # No sign change found: FAR and FRR never cross (fully separated scores
    # across the whole observed range, or a degenerate single-class sweep).
    last = usable[-1]
    if diffs[-1] <= 0 and diffs[0] <= 0:
        m = min(usable, key=lambda m: abs(m.far - m.frr))
        return EerResult((m.far + m.frr) / 2, m.threshold, m.far, m.frr, "no_crossing_found_nearest_point_fallback")
    m = min(usable, key=lambda m: abs(m.far - m.frr))
    return EerResult((m.far + m.frr) / 2, m.threshold, m.far, m.frr, "no_crossing_found_nearest_point_fallback")


# ---------------------------------------------------------------------------
# Score distribution statistics + overlap quantification
# ---------------------------------------------------------------------------
def distribution_stats(values: np.ndarray) -> dict:
    if values.size == 0:
        return {"count": 0}
    percentiles = np.percentile(values, [5, 25, 50, 75, 95])
    return {
        "count": int(values.size),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "p5": float(percentiles[0]),
        "p25": float(percentiles[1]),
        "p50": float(percentiles[2]),
        "p75": float(percentiles[3]),
        "p95": float(percentiles[4]),
    }


def overlap_analysis(genuine: np.ndarray, impostor: np.ndarray, bins: int = 50) -> dict:
    lo = float(min(genuine.min(), impostor.min()))
    hi = float(max(genuine.max(), impostor.max()))
    edges = np.linspace(lo, hi, bins + 1)
    g_hist, _ = np.histogram(genuine, bins=edges)
    i_hist, _ = np.histogram(impostor, bins=edges)
    g_norm = g_hist / g_hist.sum() if g_hist.sum() else g_hist.astype(float)
    i_norm = i_hist / i_hist.sum() if i_hist.sum() else i_hist.astype(float)
    overlap_coefficient = float(np.sum(np.minimum(g_norm, i_norm)))

    genuine_p5 = float(np.percentile(genuine, 5))
    impostor_p95 = float(np.percentile(impostor, 95))
    frac_impostor_above_genuine_p5 = float(np.mean(impostor >= genuine_p5))
    frac_genuine_below_impostor_p95 = float(np.mean(genuine <= impostor_p95))

    return {
        "histogram_overlap_coefficient": overlap_coefficient,
        "histogram_bins": bins,
        "genuine_p5": genuine_p5,
        "impostor_p95": impostor_p95,
        "fraction_impostor_scores_at_or_above_genuine_p5": frac_impostor_above_genuine_p5,
        "fraction_genuine_scores_at_or_below_impostor_p95": frac_genuine_below_impostor_p95,
        "interpretation": (
            "The histogram overlap coefficient is the fraction of the total (normalized) "
            "score mass shared between the genuine and impostor distributions on a common "
            f"{bins}-bin grid (0 = fully separated, 1 = identical distributions). The "
            "percentile-crossing fractions quantify, directly in FAR/FRR terms, how much "
            "impostor mass sits at or above the genuine distribution's lower tail (relevant "
            "to FAR at a conservative/high threshold) and how much genuine mass sits at or "
            "below the impostor distribution's upper tail (relevant to FRR at a permissive/"
            "low threshold) -- this is the mechanical driver of the FAR/FRR tradeoff observed "
            "in the threshold sweep: any threshold placed inside the overlap region necessarily "
            "trades some FAR for some FRR."
        ),
    }


# ---------------------------------------------------------------------------
# Bootstrap confidence intervals -- identity-level resampling (requirement
# #5/#8): pairs sharing an identity are not independent observations, so the
# resampling unit is the identity, not the raw pair.
# ---------------------------------------------------------------------------
@dataclass
class BootstrapCI:
    metric: str
    threshold_label: str
    point_estimate: float | None
    ci_low: float | None
    ci_high: float | None
    n_iterations: int
    n_invalid_iterations: int
    method: str

    def to_dict(self) -> dict:
        return dict(vars(self))


def _rebuild_pairs_for_identity_multiset(
    identity_multiset: list[str],
    selected: dict[str, list[Path]],
    outcomes: dict[Path, ImageOutcome],
    impostor_target_count: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Re-runs genuine+impostor pair generation on a (possibly-repeated)
    resampled identity list, using virtual per-occurrence identity keys so a
    twice-drawn identity contributes its pairs twice (standard cluster-
    bootstrap semantics), then scores those pairs from the ALREADY-COMPUTED
    embedding cache (no re-inference -- pure numpy, fast)."""
    virtual_selected: dict[str, list[Path]] = {}
    for occurrence_index, real_identity in enumerate(identity_multiset):
        virtual_key = f"{real_identity}#{occurrence_index}"
        virtual_selected[virtual_key] = selected[real_identity]

    genuine_pairs = generate_genuine_pairs(virtual_selected)
    impostor_pairs = generate_impostor_pairs(virtual_selected, impostor_target_count, seed)

    all_scores: list[float] = []
    all_labels: list[int] = []
    for p in genuine_pairs + impostor_pairs:
        oa, ob = outcomes.get(p.image_a), outcomes.get(p.image_b)
        if oa is None or ob is None or oa.status != "success" or ob.status != "success":
            continue
        all_scores.append(_cosine_similarity(oa.embedding, ob.embedding))
        all_labels.append(p.label)
    return np.array(all_scores), np.array(all_labels)


def bootstrap_confidence_intervals(
    identities: list[str],
    selected: dict[str, list[Path]],
    outcomes: dict[Path, ImageOutcome],
    impostor_target_count: int,
    thresholds: dict[str, float],
    n_iterations: int,
    seed: int,
) -> list[BootstrapCI]:
    from sklearn.metrics import roc_auc_score

    rng = random.Random(seed)
    metric_names = ["far", "frr", "accuracy", "precision", "recall", "f1"]
    samples: dict[str, dict[str, list[float]]] = {
        label: {m: [] for m in metric_names + ["auc"]} for label in thresholds
    }
    invalid_counts: dict[str, dict[str, int]] = {label: {m: 0 for m in metric_names + ["auc"]} for label in thresholds}

    for it in range(n_iterations):
        iter_seed = seed + it + 1
        resampled = [rng.choice(identities) for _ in range(len(identities))]
        scores, labels = _rebuild_pairs_for_identity_multiset(
            resampled, selected, outcomes, impostor_target_count, iter_seed
        )
        if scores.size == 0 or len(np.unique(labels)) < 2:
            for label in thresholds:
                for m in metric_names + ["auc"]:
                    invalid_counts[label][m] += 1
            continue

        try:
            auc = roc_auc_score(labels, scores)
        except ValueError:
            auc = None

        for label, threshold in thresholds.items():
            m = evaluate_at_threshold(scores, labels, threshold)
            values = {
                "far": m.far,
                "frr": m.frr,
                "accuracy": m.accuracy,
                "precision": m.precision,
                "recall": m.recall,
                "f1": m.f1,
                "auc": auc,
            }
            for name, value in values.items():
                if value is None:
                    invalid_counts[label][name] += 1
                else:
                    samples[label][name].append(value)

    results: list[BootstrapCI] = []
    for label in thresholds:
        for name in metric_names + ["auc"]:
            vals = samples[label][name]
            if len(vals) < 2:
                results.append(
                    BootstrapCI(
                        name, label, None, None, None, n_iterations, invalid_counts[label][name],
                        "insufficient valid bootstrap iterations to compute a percentile CI",
                    )
                )
                continue
            lo, hi = np.percentile(vals, BOOTSTRAP_CI_PERCENTILES)
            results.append(
                BootstrapCI(
                    name, label, float(np.mean(vals)), float(lo), float(hi),
                    n_iterations, invalid_counts[label][name],
                    f"percentile bootstrap, identity-level resampling, {n_iterations} iterations, "
                    f"seed={seed}, CI={BOOTSTRAP_CI_PERCENTILES}",
                )
            )
    return results


# ---------------------------------------------------------------------------
# Error analysis -- observational correlates only (blur variance, face bbox
# size), reusing the REAL production detection function
# (face_recognition.pipeline._detect_single_face /
# face_recognition.pipeline._laplacian_sharpness) rather than a second
# reimplementation, applied only to the false-accept/false-reject subset.
# ---------------------------------------------------------------------------
@dataclass
class ErrorRecord:
    identity_a: str
    identity_b: str
    image_a: str
    image_b: str
    label: int
    predicted: int
    similarity: float
    threshold_label: str
    blur_variance_a: float | None
    blur_variance_b: float | None
    bbox_area_a: float | None
    bbox_area_b: float | None


def _image_quality_proxies(path: Path) -> tuple[float | None, float | None]:
    from face_recognition.pipeline import _detect_single_face, _laplacian_sharpness, decode_image

    try:
        image_bgr = decode_image(path.read_bytes())
        face = _detect_single_face(image_bgr)
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        bbox_area = float(max(0, x2 - x1) * max(0, y2 - y1))
        x1c, y1c = max(x1, 0), max(y1, 0)
        crop = image_bgr[y1c:y2, x1c:x2]
        if crop.size == 0:
            return None, bbox_area
        import cv2

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return _laplacian_sharpness(gray), bbox_area
    except Exception:
        return None, None


def error_analysis(scored: list[ScoredPair], threshold_label: str, threshold: float) -> dict:
    false_accepts = [p for p in scored if p.label == 0 and p.similarity >= threshold]
    false_rejects = [p for p in scored if p.label == 1 and p.similarity < threshold]

    records: list[ErrorRecord] = []
    for p in false_accepts + false_rejects:
        blur_a, bbox_a = _image_quality_proxies(p.image_a)
        blur_b, bbox_b = _image_quality_proxies(p.image_b)
        predicted = 1 if p.similarity >= threshold else 0
        records.append(
            ErrorRecord(
                p.identity_a, p.identity_b, str(p.image_a), str(p.image_b), p.label, predicted,
                p.similarity, threshold_label, blur_a, blur_b, bbox_a, bbox_b,
            )
        )

    def _correlate(records: list[ErrorRecord], kind: str) -> str:
        subset = [r for r in records if (r.label == 0) == (kind == "false_accept")]
        blurs = [b for r in subset for b in (r.blur_variance_a, r.blur_variance_b) if b is not None]
        if not blurs:
            return f"No {kind} records with a usable blur-variance proxy were found."
        return (
            f"{len(subset)} {kind} pair(s) analyzed; measured blur-variance (Laplacian, higher "
            f"= sharper) across their images: mean={np.mean(blurs):.1f}, "
            f"median={np.median(blurs):.1f}. Blur variance is reported here as an observed "
            "correlate only -- not established as a causal explanation for any individual "
            "decision."
        )

    return {
        "false_accept_count": len(false_accepts),
        "false_reject_count": len(false_rejects),
        "threshold_label": threshold_label,
        "threshold_value": threshold,
        "false_accept_blur_note": _correlate(records, "false_accept"),
        "false_reject_blur_note": _correlate(records, "false_reject"),
        "records": [vars(r) for r in records],
    }


# ---------------------------------------------------------------------------
# Environment / model identity record
# ---------------------------------------------------------------------------
def get_environment_info(actual_gpu_providers: dict[str, list[str]] | None) -> dict:
    def _version(pkg: str) -> str:
        try:
            return importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            return "not installed"

    import cv2

    model_dir = Path.home() / ".insightface" / "models" / "buffalo_l"
    det_path = model_dir / "det_10g.onnx"
    rec_path = model_dir / "w600k_r50.onnx"

    execution_provider_note = (
        "CPUExecutionProvider (matches production ai/face_recognition/pipeline.py exactly)"
        if not GPU_MODE
        else (
            "DEVIATION FROM PRODUCTION, EXPLICITLY USER-DIRECTED: production hard-codes "
            "CPUExecutionProvider/ctx_id=-1 (ai/face_recognition/pipeline.py, unmodified by "
            "this script). This run instead pre-seeded the same production analyze() "
            "pipeline's model singleton with CUDAExecutionProvider (GPU device "
            f"{GPU_DEVICE_ID}) for speed. Detection/embedding LOGIC, model weights, alignment, "
            "and similarity computation are otherwise byte-identical to production -- only the "
            "ONNX execution backend differs. Actual per-model providers reported by ONNXRuntime: "
            f"{actual_gpu_providers}. This evaluation therefore does NOT measure production's "
            "actual deployed configuration and must not be cited as such."
        )
    )

    return {
        "python_version": platform.python_version(),
        "os": platform.platform(),
        "insightface_version": _version("insightface"),
        "onnxruntime_version": _version("onnxruntime-gpu" if GPU_MODE else "onnxruntime"),
        "opencv_version": cv2.__version__,
        "numpy_version": np.__version__,
        "scikit_learn_version": _version("scikit-learn"),
        "matplotlib_version": _version("matplotlib"),
        "model_pack": "buffalo_l",
        "detector": "SCRFD (det_10g.onnx) -- repository docstring calls this 'RetinaFace' "
        "loosely; SCRFD is the actual detector shipped in this InsightFace model pack",
        "embedding_model": "ArcFace, ResNet-50 backbone (w600k_r50.onnx)",
        "embedding_dimension": face_pipeline.EMBEDDING_DIMENSION,
        "execution_provider": "CUDAExecutionProvider" if GPU_MODE else "CPUExecutionProvider",
        "execution_provider_note": execution_provider_note,
        "gpu_mode": GPU_MODE,
        "actual_onnx_providers_per_model": actual_gpu_providers,
        "det_size": [640, 640],
        "production_similarity_threshold": PRODUCTION_THRESHOLD,
        "det_model_sha256": _sha256_file(det_path) if det_path.exists() else None,
        "rec_model_sha256": _sha256_file(rec_path) if rec_path.exists() else None,
        "model_files_found": det_path.exists() and rec_path.exists(),
    }


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------
def make_plots(
    genuine_scores: np.ndarray,
    impostor_scores: np.ndarray,
    coarse_sweep: list[ThresholdMetrics],
    roc_fpr: np.ndarray,
    roc_tpr: np.ndarray,
    auc_value: float,
    eer: EerResult,
    confusion_matrices: dict[str, ThresholdMetrics],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # similarity_distribution.png
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(genuine_scores, bins=40, alpha=0.6, label="genuine pairs", color="tab:blue", density=True)
    ax.hist(impostor_scores, bins=40, alpha=0.6, label="impostor pairs", color="tab:red", density=True)
    ax.axvline(PRODUCTION_THRESHOLD, color="black", linestyle="--", label=f"production threshold ({PRODUCTION_THRESHOLD})")
    ax.axvline(eer.threshold, color="green", linestyle=":", label=f"EER threshold ({eer.threshold:.3f})")
    ax.set_xlabel("cosine similarity")
    ax.set_ylabel("density")
    ax.set_title("Similarity score distributions (measured, this evaluation)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "similarity_distribution.png", dpi=150)
    plt.close(fig)

    # threshold_analysis.png (coarse grid, visualization only)
    thresholds = [m.threshold for m in coarse_sweep]
    far = [m.far if m.far is not None else np.nan for m in coarse_sweep]
    frr = [m.frr if m.frr is not None else np.nan for m in coarse_sweep]
    precision = [m.precision if m.precision is not None else np.nan for m in coarse_sweep]
    recall = [m.recall if m.recall is not None else np.nan for m in coarse_sweep]
    f1 = [m.f1 if m.f1 is not None else np.nan for m in coarse_sweep]
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(thresholds, far, label="FAR")
    ax.plot(thresholds, frr, label="FRR")
    ax.plot(thresholds, precision, label="Precision")
    ax.plot(thresholds, recall, label="Recall")
    ax.plot(thresholds, f1, label="F1")
    ax.axvline(PRODUCTION_THRESHOLD, color="black", linestyle="--", alpha=0.5)
    ax.set_xlabel("threshold")
    ax.set_ylabel("metric value")
    ax.set_title(f"Threshold analysis ({COARSE_GRID_POINTS}-point grid, VISUALIZATION ONLY)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "threshold_analysis.png", dpi=150)
    plt.close(fig)

    # roc_curve.png
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot(roc_fpr, roc_tpr, label=f"ROC (AUC={auc_value:.4f})")
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="chance")
    ax.scatter([eer.far_at_eer], [1 - eer.frr_at_eer], color="green", zorder=5, label=f"EER ({eer.eer:.4f})")
    ax.set_xlabel("False Accept Rate (FAR)")
    ax.set_ylabel("True Positive Rate (1 - FRR)")
    ax.set_title("ROC curve (measured, this evaluation)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "roc_curve.png", dpi=150)
    plt.close(fig)

    # confusion_matrix.png -- one labeled panel per threshold, never overwritten
    n = len(confusion_matrices)
    fig, axes = plt.subplots(1, n, figsize=(4 * n, 4))
    if n == 1:
        axes = [axes]
    for ax, (label, m) in zip(axes, confusion_matrices.items()):
        matrix = np.array([[m.tp, m.fn], [m.fp, m.tn]])
        ax.imshow(matrix, cmap="Blues")
        for (i, j), v in np.ndenumerate(matrix):
            ax.text(j, i, str(v), ha="center", va="center")
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(["Predicted Match", "Predicted No-Match"])
        ax.set_yticklabels(["Actual Match", "Actual Non-match"])
        ax.set_title(f"{label}\n(threshold={m.threshold:.4f})")
    fig.tight_layout()
    fig.savefig(RESULTS_DIR / "confusion_matrix.png", dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Reproducibility check (requirement #21) -- pure selection/pairing re-run,
# no model inference, must be byte-identical.
# ---------------------------------------------------------------------------
def reproducibility_check(eligible: dict[str, list[Path]], identity_count: int, seed: int) -> dict:
    a = select_identities_and_images(eligible, identity_count, IMAGES_PER_IDENTITY, seed)
    b = select_identities_and_images(eligible, identity_count, IMAGES_PER_IDENTITY, seed)
    identical = a == b
    genuine_a = generate_genuine_pairs(a)
    genuine_b = generate_genuine_pairs(b)
    genuine_identical = genuine_a == genuine_b
    return {
        "identity_and_image_selection_reproducible": identical,
        "genuine_pair_list_reproducible": genuine_identical,
        "note": (
            "Identity/image selection and genuine-pair generation are pure seeded-random "
            "Python operations with no floating-point model inference -- verified byte-"
            "identical across two runs with the same seed, as expected. Similarity SCORES "
            "involve ONNXRuntime CPU inference; bit-for-bit determinism of those was not "
            "separately re-verified in this run beyond ONNXRuntime's own CPU determinism "
            "guarantees for a fixed model/input on the same machine -- not independently "
            "re-measured here, reported as a known limitation rather than assumed."
        ),
    }


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        _run()
    except EvaluationFailure as exc:
        print(f"\nEVALUATION FAILED: {exc}", file=sys.stderr)
        print("No results.json or report_section.md were written.", file=sys.stderr)
        sys.exit(1)


def _run() -> None:
    print("=" * 70)
    print("Independent evaluation of the pretrained InsightFace verification pipeline")
    print("=" * 70)

    actual_gpu_providers: dict[str, list[str]] | None = None
    if GPU_MODE:
        actual_gpu_providers = configure_gpu_execution()
        print(f"Actual ONNX execution providers in use: {actual_gpu_providers}")

    root, archive_sha256, retrieved_at = download_dataset()
    identities = load_identities(root)
    dataset_wide = compute_dataset_wide_stats(identities)
    print(f"Dataset-wide: {dataset_wide.to_dict()}")

    eligible = {k: v for k, v in identities.items() if len(v) >= MIN_IMAGES_PER_PERSON}
    if not eligible:
        raise EvaluationFailure(
            f"zero identities have >= {MIN_IMAGES_PER_PERSON} images -- cannot form genuine pairs"
        )

    pilot = run_pilot_and_decide_scale(eligible, MAX_RUNTIME_MINUTES, MAX_IDENTITIES)
    print(f"Pilot result: {pilot.to_dict()}")

    selected = select_identities_and_images(eligible, pilot.selected_identities, IMAGES_PER_IDENTITY, SEED)
    identity_list = sorted(selected.keys())
    print(f"Selected {len(selected)} identities x {IMAGES_PER_IDENTITY} images.")

    all_images = [p for images in selected.values() for p in images]
    outcomes = embed_all_images(selected)
    image_processing_summary = summarize_image_processing(outcomes)
    print(f"Image processing: {image_processing_summary}")

    genuine_pairs = generate_genuine_pairs(selected)
    impostor_pairs = generate_impostor_pairs(selected, target_count=len(genuine_pairs), seed=SEED)
    print(f"Pairs generated: {len(genuine_pairs)} genuine, {len(impostor_pairs)} impostor (target-balanced)")

    scored, unusable = score_pairs(genuine_pairs + impostor_pairs, outcomes)
    if len(scored) == 0:
        raise EvaluationFailure("no pair had two successfully-embedded images -- cannot compute any metric")
    if unusable:
        print(f"NOTE: {len(unusable)} pairs excluded (one or both images failed detection/embedding)")

    scores = np.array([p.similarity for p in scored])
    labels = np.array([p.label for p in scored])
    genuine_scores = scores[labels == 1]
    impostor_scores = scores[labels == 0]
    if genuine_scores.size == 0 or impostor_scores.size == 0:
        raise EvaluationFailure(
            "after filtering unusable pairs, one of genuine/impostor score sets is empty -- "
            "cannot compute FAR/FRR/ROC"
        )

    score_dist = {
        "genuine": distribution_stats(genuine_scores),
        "impostor": distribution_stats(impostor_scores),
    }
    overlap = overlap_analysis(genuine_scores, impostor_scores)

    sweep = full_threshold_sweep(scores, labels)
    coarse_sweep = coarse_threshold_grid(scores, labels)

    eer = interpolated_eer(sweep)
    max_f1 = find_max_f1(sweep)
    target_far_result = find_target_far_threshold(sweep, TARGET_FAR)
    production_result = evaluate_at_threshold(scores, labels, PRODUCTION_THRESHOLD)

    from sklearn.metrics import roc_auc_score, roc_curve

    roc_fpr, roc_tpr, _roc_thresholds = roc_curve(labels, scores)
    auc_value = float(roc_auc_score(labels, scores))

    threshold_labels = {
        "production_threshold_0.6": PRODUCTION_THRESHOLD,
        "eer_threshold": eer.threshold,
    }
    print(f"Running bootstrap CIs ({BOOTSTRAP_ITERATIONS} iterations, identity-level resampling)...")
    cis = bootstrap_confidence_intervals(
        identity_list, selected, outcomes, len(genuine_pairs), threshold_labels, BOOTSTRAP_ITERATIONS, SEED
    )

    errors_production = error_analysis(scored, "production_threshold_0.6", PRODUCTION_THRESHOLD)
    errors_eer = error_analysis(scored, "eer_threshold", eer.threshold)

    environment = get_environment_info(actual_gpu_providers)
    repro = reproducibility_check(eligible, pilot.selected_identities, SEED)

    confusion_matrices = {
        "production_threshold_0.6": production_result,
        "eer_threshold": interpolated_eer_as_metrics(scores, labels, eer),
        "max_f1_threshold": evaluate_at_threshold(scores, labels, max_f1.threshold),
    }
    if target_far_result is not None:
        confusion_matrices[f"target_far_{TARGET_FAR}"] = target_far_result

    make_plots(genuine_scores, impostor_scores, coarse_sweep, roc_fpr, roc_tpr, auc_value, eer, confusion_matrices)

    results = {
        "objective": "Independent evaluation of the pretrained InsightFace verification pipeline "
        "used by SmartAttendanceAI, on an independent public dataset. No training or "
        "fine-tuning performed. 1:1, pair-based face verification.",
        "dataset": {
            "source": "LFW (Labeled Faces in the Wild), deep-funneled",
            "download_url": LFW_URL,
            "archive_sha256": archive_sha256,
            "retrieved_at_utc": retrieved_at,
            "license_verification": LICENSE_VERIFICATION_NOTE,
            "dataset_wide": dataset_wide.to_dict(),
            "evaluation_subset": {
                "selection_seed": SEED,
                "min_images_per_person": MIN_IMAGES_PER_PERSON,
                "images_per_identity": IMAGES_PER_IDENTITY,
                "selected_identities": len(selected),
                "selected_images": len(all_images),
                "selection_algorithm": (
                    "identities with >= MIN_IMAGES_PER_PERSON images sorted by name; if capped, "
                    "random.Random(SEED).sample() of that sorted list; for each selected "
                    "identity, random.Random(SEED).sample() of IMAGES_PER_IDENTITY images from "
                    "its available images (or all of them if fewer are available than the cap)"
                ),
            },
            "pilot": pilot.to_dict(),
        },
        "environment": environment,
        "pipeline_config": {
            "model_pack": "buffalo_l",
            "detector": "SCRFD (det_10g.onnx)",
            "embedding_model": "ArcFace ResNet-50 (w600k_r50.onnx)",
            "embedding_dimension": face_pipeline.EMBEDDING_DIMENSION,
            "execution_provider": "CUDAExecutionProvider" if GPU_MODE else "CPUExecutionProvider",
            "execution_provider_matches_production": not GPU_MODE,
            "det_size": [640, 640],
            "similarity_function": "dot product of two L2-normalized embeddings (equivalent to "
            "cosine similarity) -- reimplemented locally, verified bit-identical to "
            "app.services.face_service._cosine_similarity by "
            "test_evaluate_face_verification.py::test_cosine_similarity_matches_production",
            "scope_note": "liveness (a separate gate in production, run before similarity) is "
            "OUT OF SCOPE for this evaluation -- only detection+embedding+similarity+threshold "
            "is evaluated here",
        },
        "image_processing": image_processing_summary,
        "pairs": {
            "genuine_count": len(genuine_pairs),
            "impostor_count": len(impostor_pairs),
            "usable_pairs_after_embedding_failures": len(scored),
            "unusable_pairs": len(unusable),
            "generation_algorithm": (
                "genuine: for each selected identity, all C(k,2) unique unordered image-index "
                "pairs (i<j), so no image is ever paired with itself and no reversed duplicate "
                "exists. impostor: seeded random.Random(SEED) sampling of (identity_a, image) x "
                "(identity_b, image) with identity_a != identity_b, deduplicated as unordered "
                "pairs, target count = genuine pair count (1:1 balanced). Verification is 1:1, "
                "pair-based -- not template-based, not 1:N identification."
            ),
        },
        "score_distributions": score_dist,
        "overlap_analysis": overlap,
        "threshold_sweep": {
            "primary_method": "every unique observed similarity score used as a decision "
            "boundary (exhaustive, score-derived) -- this is the basis for every reported "
            "metric, EER, and threshold selection below",
            "visualization_only_grid_points": COARSE_GRID_POINTS,
            "full_sweep": [m.to_dict() for m in sweep],
        },
        "production_threshold_result": production_result.to_dict(),
        "selected_thresholds": {
            "eer": eer.to_dict(),
            "max_f1": max_f1.to_dict(),
            "target_far": {
                "target": TARGET_FAR,
                "achieved": target_far_result.to_dict() if target_far_result else None,
                "achievable": target_far_result is not None,
            },
        },
        "roc_auc": {
            "auc": auc_value,
            "fpr": roc_fpr.tolist(),
            "tpr": roc_tpr.tolist(),
        },
        "confusion_matrices": {k: v.to_dict() for k, v in confusion_matrices.items()},
        "confidence_intervals": [ci.to_dict() for ci in cis],
        "error_analysis": {
            "production_threshold_0.6": errors_production,
            "eer_threshold": errors_eer,
        },
        "reproducibility": {
            "seed": SEED,
            "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
            **repro,
        },
        "threshold_comparison_table": [
            {"label": "A. current production threshold", "threshold": PRODUCTION_THRESHOLD, **production_result.to_dict()},
            {"label": "B. EER threshold (experimental)", "threshold": eer.threshold, **evaluate_at_threshold(scores, labels, eer.threshold).to_dict()},
            {"label": "C. max-F1 threshold (experimental)", "threshold": max_f1.threshold, **max_f1.to_dict()},
            (
                {"label": f"D. target-FAR<={TARGET_FAR} threshold (experimental)", "threshold": target_far_result.threshold, **target_far_result.to_dict()}
                if target_far_result
                else {"label": f"D. target-FAR<={TARGET_FAR} threshold (experimental)", "achievable": False}
            ),
        ],
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_json_path = RESULTS_DIR / "results.json"
    with open(results_json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Wrote {results_json_path}")

    results_csv_path = RESULTS_DIR / "results.csv"
    with open(results_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["identity_a", "identity_b", "image_a", "image_b", "label", "similarity"])
        for p in scored:
            writer.writerow([p.identity_a, p.identity_b, str(p.image_a), str(p.image_b), p.label, p.similarity])
    print(f"Wrote {results_csv_path}")

    errors_csv_path = RESULTS_DIR / "errors.csv"
    with open(errors_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["threshold_label", "identity_a", "identity_b", "image_a", "image_b", "label", "predicted",
             "similarity", "blur_variance_a", "blur_variance_b", "bbox_area_a", "bbox_area_b"]
        )
        for err in (errors_production, errors_eer):
            for r in err["records"]:
                writer.writerow(
                    [r["threshold_label"], r["identity_a"], r["identity_b"], r["image_a"], r["image_b"],
                     r["label"], r["predicted"], r["similarity"], r["blur_variance_a"], r["blur_variance_b"],
                     r["bbox_area_a"], r["bbox_area_b"]]
                )
    print(f"Wrote {errors_csv_path}")

    report_path = RESULTS_DIR / "report_section.md"
    report_text = generate_report_section(results)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"Wrote {report_path}")

    print("\nDone. All outputs in", RESULTS_DIR)


def interpolated_eer_as_metrics(scores: np.ndarray, labels: np.ndarray, eer: EerResult) -> ThresholdMetrics:
    return evaluate_at_threshold(scores, labels, eer.threshold)


# ---------------------------------------------------------------------------
# Academic report generation -- ONLY called after results.json is complete;
# reads exclusively from the `results` dict just built, never a template
# with placeholder numbers.
# ---------------------------------------------------------------------------
def generate_report_section(r: dict) -> str:
    ds = r["dataset"]
    dw = ds["dataset_wide"]
    es = ds["evaluation_subset"]
    ip = r["image_processing"]
    pairs = r["pairs"]
    sd = r["score_distributions"]
    ov = r["overlap_analysis"]
    prod = r["production_threshold_result"]
    eer = r["selected_thresholds"]["eer"]
    maxf1 = r["selected_thresholds"]["max_f1"]
    target = r["selected_thresholds"]["target_far"]
    env = r["environment"]
    repro = r["reproducibility"]

    def fmt(v, pct=False, digits=4):
        if v is None:
            return "N/A"
        return f"{v * 100:.2f}%" if pct else f"{v:.{digits}f}"

    ci_by_key = {(c["metric"], c["threshold_label"]): c for c in r["confidence_intervals"]}

    def ci_str(metric: str, threshold_label: str) -> str:
        c = ci_by_key.get((metric, threshold_label))
        if not c or c["ci_low"] is None:
            return "CI not computable"
        return f"[{c['ci_low']:.4f}, {c['ci_high']:.4f}] (n_invalid={c['n_invalid_iterations']})"

    lines: list[str] = []
    lines.append("# Evaluation of the Pretrained InsightFace Verification Pipeline\n")

    lines.append("## 1. Objective\n")
    lines.append(
        "This section reports an independent evaluation of the pretrained InsightFace "
        "face-verification pipeline already deployed in SmartAttendanceAI, measured against "
        "the public LFW dataset. No model training or fine-tuning was performed at any point. "
        "All figures below are experimentally measured in this run; none are copied from "
        "published benchmarks or estimated.\n"
    )

    lines.append("## 2. Evaluated Pipeline\n")
    lines.append(
        f"InsightFace Buffalo_L -> {env['detector']} -> InsightFace's internal 5-point landmark "
        f"alignment/normalization -> {env['embedding_model']} -> "
        f"{env['embedding_dimension']}-dimensional L2-normalized embedding -> cosine similarity "
        f"-> threshold. Detection size: {env['det_size']}. This is 1:1, pair-based face "
        "verification -- not 1:N identification. Liveness detection (a separate gate in "
        "production, evaluated before similarity) is explicitly out of scope for this "
        "evaluation.\n\n"
    )
    if env["gpu_mode"]:
        lines.append(
            "**Execution provider deviation (explicit, user-directed):** "
            f"{env['execution_provider_note']}\n"
        )
    else:
        lines.append(f"Execution provider: {env['execution_provider']} (matches production).\n")

    lines.append("## 3. Dataset\n")
    lines.append(
        f"Source: {ds['source']}, downloaded from {ds['download_url']} "
        f"(archive SHA-256: {ds['archive_sha256']}), retrieved {ds['retrieved_at_utc']}.\n\n"
        f"**License**: {ds['license_verification']}\n\n"
        f"Dataset-wide (measured from the actual downloaded/extracted archive): "
        f"{dw['total_identities']} identities, {dw['total_images']} images; "
        f"{dw['identities_with_2plus_images']} identities have >= 2 images; "
        f"{dw['identities_with_min_images']} identities have >= {es['min_images_per_person']} "
        f"images ({dw['images_in_identities_with_min_images']} images total among those).\n"
    )

    lines.append("## 4. Dataset Selection\n")
    pilot = ds["pilot"]
    lines.append(
        f"Selection seed: {es['selection_seed']}. Algorithm: {es['selection_algorithm']}. "
        f"Selected {es['selected_identities']} identities x {es['images_per_identity']} images "
        f"= {es['selected_images']} images, out of {pilot['total_eligible_identities']} "
        f"eligible identities ({pilot['total_eligible_images']} eligible images).\n\n"
    )
    if pilot["cap_applied"]:
        lines.append(f"**A cap was applied.** Reason: {pilot['cap_reason']}\n")
    else:
        lines.append(
            "No identity cap was applied -- every eligible identity was used. Pilot timing: "
            f"{pilot['mean_seconds_per_image']:.3f}s/image (measured over "
            f"{pilot['images_timed']} images), projected full-set runtime "
            f"{pilot['projected_full_runtime_minutes']:.1f} minutes against a budget of "
            f"{pilot['max_runtime_minutes']} minutes.\n"
        )

    lines.append("\n## 5. Experimental Protocol\n")
    lines.append(
        "Every selected image was passed through `face_recognition.pipeline.analyze()` -- the "
        "exact production entry point -- exactly once; embeddings were cached and reused across "
        "all pairs referencing that image. Similarity is the dot product of two L2-normalized "
        "512-d embeddings (mathematically equivalent to cosine similarity), verified bit-"
        "identical to production's `_cosine_similarity` by a dedicated equivalence test.\n"
    )

    lines.append("## 6. Image Processing Success/Failure\n")
    lines.append(
        f"Total images: {ip['total_images']}. Successful embeddings: "
        f"{ip['successful_embeddings']} ({fmt(ip['success_rate'], pct=True)}). Failed: "
        f"{ip['failed_images']} ({fmt(ip['failure_rate'], pct=True)}). Failure reasons: "
        f"{ip['failure_reason_counts']}.\n"
    )

    lines.append("## 7. Genuine and Impostor Pair Construction\n")
    lines.append(
        f"{pairs['generation_algorithm']} Genuine pairs: {pairs['genuine_count']}. Impostor "
        f"pairs: {pairs['impostor_count']}. Usable pairs after excluding images that failed "
        f"detection/embedding: {pairs['usable_pairs_after_embedding_failures']} "
        f"({pairs['unusable_pairs']} pairs excluded).\n"
    )

    lines.append("## 8. Similarity Score Analysis\n")
    lines.append("| Statistic | Genuine | Impostor |\n|---|---|---|\n")
    for key, label in [
        ("count", "Count"), ("mean", "Mean"), ("median", "Median"), ("std", "Std"),
        ("min", "Min"), ("max", "Max"), ("p5", "P5"), ("p25", "P25"), ("p50", "P50"),
        ("p75", "P75"), ("p95", "P95"),
    ]:
        lines.append(f"| {label} | {fmt(sd['genuine'].get(key), digits=4)} | {fmt(sd['impostor'].get(key), digits=4)} |\n")
    lines.append(
        f"\nDistribution overlap coefficient ({ov['histogram_bins']} shared bins): "
        f"{ov['histogram_overlap_coefficient']:.4f}. {ov['fraction_impostor_scores_at_or_above_genuine_p5'] * 100:.2f}% "
        f"of impostor scores are at or above the genuine distribution's P5; "
        f"{ov['fraction_genuine_scores_at_or_below_impostor_p95'] * 100:.2f}% of genuine scores are at or below "
        f"the impostor distribution's P95. {ov['interpretation']}\n"
    )

    lines.append("## 9. Threshold Evaluation\n")
    lines.append(
        "Every unique observed similarity score was used as a decision boundary (exhaustive, "
        "score-derived) -- the primary basis for every metric below. A coarse "
        f"{r['threshold_sweep']['visualization_only_grid_points']}-point grid was used only for "
        "the threshold_analysis.png visualization, never for a reported metric.\n"
    )

    lines.append("## 10. ROC/AUC Analysis\n")
    lines.append(f"Measured AUC: {r['roc_auc']['auc']:.4f} (95% bootstrap CI at production threshold: "
                  f"{ci_str('auc', 'production_threshold_0.6')}).\n")

    lines.append("## 11. EER Analysis\n")
    lines.append(
        f"Empirical EER estimate on this evaluation dataset/subset: {fmt(eer['eer'], pct=True)}, "
        f"at threshold {eer['threshold']:.4f} (FAR={fmt(eer['far_at_eer'], pct=True)}, "
        f"FRR={fmt(eer['frr_at_eer'], pct=True)}). Method: {eer['method']}. This is a "
        "population-agnostic empirical estimate on this specific dataset/subset, not a "
        "closed-form or universal value.\n"
    )

    lines.append("## 12. Production Threshold Evaluation\n")
    lines.append(
        f"At the current production threshold ({r['pipeline_config']['similarity_function'] and '0.6'}): "
        f"Accuracy={fmt(prod['accuracy'])}, Precision={fmt(prod['precision'])}, "
        f"Recall={fmt(prod['recall'])}, F1={fmt(prod['f1'])}, FAR={fmt(prod['far'], pct=True)}, "
        f"FRR={fmt(prod['frr'], pct=True)}, Specificity={fmt(prod['specificity'])}. "
        f"TP={prod['tp']} TN={prod['tn']} FP={prod['fp']} FN={prod['fn']}.\n"
    )

    lines.append("## 13. Alternative Threshold Analysis\n")
    lines.append("| Threshold | Value | FAR | FRR | Precision | Recall | F1 | Accuracy |\n"
                  "|---|---|---|---|---|---|---|---|\n")
    for row in r["threshold_comparison_table"]:
        if row.get("achievable") is False:
            lines.append(f"| {row['label']} | -- | not achievable within observed score range | | | | | |\n")
            continue
        lines.append(
            f"| {row['label']} | {row['threshold']:.4f} | {fmt(row.get('far'), pct=True)} | "
            f"{fmt(row.get('frr'), pct=True)} | {fmt(row.get('precision'))} | "
            f"{fmt(row.get('recall'))} | {fmt(row.get('f1'))} | {fmt(row.get('accuracy'))} |\n"
        )
    lines.append(
        "\nThese are experimentally evaluated thresholds on this dataset, reported for "
        "comparison. None of them is applied to the running SmartAttendanceAI configuration -- "
        "`face_similarity_threshold` remains 0.6 in `backend/app/config/settings.py`, unmodified "
        "by this evaluation. Any of B/C/D is, at most, a candidate for further field piloting, "
        "not a recommended replacement.\n"
    )

    lines.append("## 14. Confidence Intervals\n")
    lines.append(
        f"95% percentile bootstrap CIs, identity-level resampling (identities resampled with "
        f"replacement, not raw pairs -- pairs sharing an identity are not independent "
        f"observations), seed={repro['seed']}, {repro['bootstrap_iterations']} iterations.\n\n"
    )
    lines.append("| Metric | Production threshold (0.6) 95% CI | EER threshold 95% CI |\n|---|---|---|\n")
    for metric in ["far", "frr", "accuracy", "precision", "recall", "f1", "auc"]:
        lines.append(
            f"| {metric.upper()} | {ci_str(metric, 'production_threshold_0.6')} | "
            f"{ci_str(metric, 'eer_threshold')} |\n"
        )

    lines.append("\n## 15. Error Analysis\n")
    ea_prod = r["error_analysis"]["production_threshold_0.6"]
    lines.append(
        f"At the production threshold: {ea_prod['false_accept_count']} false accepts, "
        f"{ea_prod['false_reject_count']} false rejects (measured counts, reported before any "
        f"correlational analysis).\n\n{ea_prod['false_accept_blur_note']}\n\n"
        f"{ea_prod['false_reject_blur_note']}\n\n"
        "Note: LFW provides no pose/lighting/expression/demographic attribute labels for the "
        "images used here, so this evaluation does not assign error causes to those categories. "
        "Only blur-variance and detected-face bounding-box size, both directly computable from "
        "the data, are reported as observational correlates.\n"
    )

    lines.append("## 16. Limitations\n")
    if env["gpu_mode"]:
        lines.append(
            "- **This evaluation ran on GPU (CUDAExecutionProvider), NOT on production's "
            "CPU-only configuration** (CPUExecutionProvider, ctx_id=-1, hard-coded in "
            "ai/face_recognition/pipeline.py and unmodified by this script). This was an "
            "explicit, informed tradeoff: prioritizing evaluation speed over exact deployment-"
            "configuration fidelity. Model weights, alignment, embedding logic, and similarity "
            "computation are otherwise identical to production. The numbers below should be "
            "read as measuring the pretrained InsightFace Buffalo_L model's discriminative "
            "accuracy, not as a reproduction of production's exact runtime configuration.\n"
        )
    lines.append(
        "- Measured performance is **on this LFW evaluation subset**, not on real "
        "SmartAttendanceAI users -- LFW consists of press-photo-style images of public figures, "
        "systematically different from enrollment/check-in selfies (camera type, distance, "
        "angle, lighting, compression, deliberate posing) and this evaluation makes no claim "
        "that these numbers transfer to production usage.\n"
        "- Demographic coverage of the evaluation subset was not separately characterized -- "
        "LFW itself is documented elsewhere as skewed toward certain demographics relative to "
        "the general population; this was not independently re-verified here and is not "
        "claimed to be representative of SmartAttendanceAI's actual user base.\n"
        "- The EER, max-F1, and target-FAR thresholds are empirical estimates on this dataset/"
        "subset only, not universal constants.\n"
        f"- License/usage terms for LFW {ds['license_verification']}\n"
        "- Liveness detection (a separate production gate) was not evaluated here.\n"
        "- Any InsightFace/ArcFace performance figures published by the model authors "
        "elsewhere (e.g. their own LFW benchmark numbers) are NOT reproduced or referenced in "
        "this results section -- every number above was measured in this experiment. If such a "
        "published figure is ever cited alongside this report, it must be labeled 'published by "
        "the model authors, not measured in this experiment' and never merged with this table.\n"
    )

    lines.append("## 17. Reproducibility\n")
    lines.append(
        f"Seed={repro['seed']} throughout. Identity/image selection and genuine-pair generation "
        f"reproducibility check: "
        f"{'PASSED (byte-identical across two runs)' if repro['identity_and_image_selection_reproducible'] and repro['genuine_pair_list_reproducible'] else 'FAILED -- see raw results.json'}. "
        f"{repro['note']}\n"
    )

    return "".join(lines)


if __name__ == "__main__":
    main()
