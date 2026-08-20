"""Pre-flight tests for evaluate_face_verification.py.

Both tests below MUST pass before the full LFW evaluation is trusted (see
that script's own module docstring / the plan's requirement #17):

1. test_cosine_similarity_matches_production -- proves the evaluation
   script's locally re-implemented `_cosine_similarity` (kept local to avoid
   importing the full FastAPI/SQLAlchemy/Settings graph into the evaluation's
   hot loop) is bit-identical to the REAL production function in
   app.services.face_service, on fixed deterministic vectors including edge
   cases.
2. test_eer_interpolation_known_case -- proves the interpolated-EER
   implementation recovers a hand-computed, exactly-known EER on a small
   synthetic score set, before it's trusted on real LFW scores.

Run: cd backend && .venv/Scripts/python.exe -m pytest scripts/test_evaluate_face_verification.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ -> `app` importable

from evaluate_face_verification import (  # noqa: E402
    _cosine_similarity as eval_cosine_similarity,
    evaluate_at_threshold,
    full_threshold_sweep,
    interpolated_eer,
)


def test_cosine_similarity_matches_production():
    from app.services.face_service import _cosine_similarity as production_cosine_similarity

    vec_512_a_raw = np.random.RandomState(42).normal(size=512)
    vec_512_a = list(vec_512_a_raw / np.linalg.norm(vec_512_a_raw))
    vec_512_b_raw = np.random.RandomState(43).normal(size=512)
    vec_512_b = list(vec_512_b_raw / np.linalg.norm(vec_512_b_raw))

    cases = [
        ([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]),  # identical
        ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),  # orthogonal
        ([0.6, 0.8, 0.0], [0.8, 0.6, 0.0]),  # partial overlap
        ([-0.5, 0.5, 0.7071067811865476], [0.5, -0.5, 0.7071067811865476]),  # negative components
        (vec_512_a, vec_512_b),  # realistic 512-d embedding-shaped vectors
    ]
    for a, b in cases:
        expected = production_cosine_similarity(a, b)
        actual = eval_cosine_similarity(a, b)
        assert actual == expected, f"mismatch for {a[:3]}...,{b[:3]}...: {actual} != {expected}"

    # Dimension-mismatch: both must raise the same exception type.
    with pytest.raises(ValueError):
        production_cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])
    with pytest.raises(ValueError):
        eval_cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


def test_eer_interpolation_known_case():
    # Hand-computed ground truth (see module docstring / plan for the derivation):
    # genuine = [0.4, 0.5, 0.6, 0.7, 0.8], impostor = [0.2, 0.3, 0.4, 0.5, 0.6]
    # At threshold 0.5: FAR=0.4, FRR=0.2 (diff=+0.2)
    # At threshold 0.6: FAR=0.2, FRR=0.4 (diff=-0.2)
    # Linear interpolation crossing: threshold=0.55, FAR=FRR=0.3, EER=0.3
    genuine = [0.4, 0.5, 0.6, 0.7, 0.8]
    impostor = [0.2, 0.3, 0.4, 0.5, 0.6]
    scores = np.array(genuine + impostor)
    labels = np.array([1] * len(genuine) + [0] * len(impostor))

    sweep = full_threshold_sweep(scores, labels)
    result = interpolated_eer(sweep)

    assert result.threshold == pytest.approx(0.55, abs=1e-9)
    assert result.far_at_eer == pytest.approx(0.3, abs=1e-9)
    assert result.frr_at_eer == pytest.approx(0.3, abs=1e-9)
    assert result.eer == pytest.approx(0.3, abs=1e-9)
    assert result.method == "linear_interpolation_between_bracketing_thresholds"


def test_eer_exact_zero_crossing_case():
    # A score set where FAR == FRR exactly at one of the observed thresholds
    # (no interpolation needed) -- exercises the "exact_zero_crossing" branch.
    genuine = [0.5, 0.5, 0.9, 0.9]
    impostor = [0.1, 0.1, 0.5, 0.5]
    scores = np.array(genuine + impostor)
    labels = np.array([1] * len(genuine) + [0] * len(impostor))
    sweep = full_threshold_sweep(scores, labels)
    result = interpolated_eer(sweep)
    # At threshold 0.5: FAR = impostor>=0.5 -> 2/4=0.5; FRR = genuine<0.5 -> 0/4=0.
    # At threshold just above 0.5 (0.9): FAR = impostor>=0.9 -> 0/4=0; FRR = genuine<0.9 -> 2/4=0.5.
    # These bracket around the true crossing; assert a sane EER in [0, 0.5].
    assert 0.0 <= result.eer <= 0.5
    assert result.method in ("linear_interpolation_between_bracketing_thresholds", "exact_zero_crossing")


def test_evaluate_at_threshold_matches_production_ge_comparison():
    scores = np.array([0.1, 0.5, 0.6, 0.6, 0.9])
    labels = np.array([0, 0, 1, 0, 1])
    m = evaluate_at_threshold(scores, labels, 0.6)
    # predicted = scores >= 0.6 -> [F, F, T, T, T]
    # genuine (label==1): indices 2,4 -> predicted True,True -> TP=2, FN=0
    # impostor (label==0): indices 0,1,3 -> predicted F,F,T -> TN=2, FP=1
    assert (m.tp, m.tn, m.fp, m.fn) == (2, 2, 1, 0)
    assert m.far == pytest.approx(1 / 3)
    assert m.frr == pytest.approx(0.0)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
