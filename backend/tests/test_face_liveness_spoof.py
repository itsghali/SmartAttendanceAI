"""Automated version of the spoof-proxy check `scripts/smoke_test_face.py`
already ran manually (TODOS.md #34) — lifted into pytest so the current
liveness heuristic's known weakness is continuously tracked instead of a
one-off manual result written down and forgotten.

Uses the REAL insightface pipeline (not mocked) — first run in a fresh
environment downloads the buffalo_l model and will be slow. Marked `slow`;
run everything with `pytest`, or exclude with `pytest -m "not slow"`.

This is a characterization test, not a security assertion: it currently
documents that a synthetic blur+moire spoof PASSES the passive liveness
heuristic (matches the manually-recorded TODOS.md result). If this test
starts failing, it means liveness got better — update/remove it as part of
whatever change caused that, don't just silence it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_AI_DIR = Path(__file__).resolve().parents[2] / "ai"
if str(_AI_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_DIR))

from face_recognition import pipeline as face_pipeline  # noqa: E402

from scripts.smoke_test_face import build_fixtures  # noqa: E402


@pytest.mark.slow
def test_liveness_heuristic_passes_synthetic_spoof(tmp_path):
    _face_a, _face_b, spoof_path = build_fixtures(tmp_path)

    with open(spoof_path, "rb") as f:
        spoof_bytes = f.read()

    result = face_pipeline.analyze(spoof_bytes)

    # Documents the known gap (TODOS.md #34): the passive heuristic (blur/
    # sharpness + FFT moire-band energy) does not reliably catch this class
    # of spoof. Recorded manual result was liveness=0.59 against a 0.5
    # threshold — both pass. Assert against the threshold, not the exact
    # value, so minor heuristic tuning doesn't flake this test while the
    # underlying weakness (heuristic, not trained classifier) is unchanged.
    from app.config.settings import get_settings

    threshold = get_settings().face_liveness_threshold
    assert result.liveness >= threshold, (
        f"liveness heuristic now correctly rejects this spoof "
        f"(score={result.liveness} < threshold={threshold}) — great, but "
        "this test documents a KNOWN GAP and needs updating, not just "
        "flipping the assertion, if the heuristic actually improved."
    )
