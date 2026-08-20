"""Requirement 2 (human-readable insights): build_presentation/render_email
tests. Covers the four spec-required questions (what/why/evidence/action),
the missing-optional-evidence case (self_n=None, self_z=None), and the
neutral-wording constraint (no misconduct/intent language anywhere in the
deterministic templates)."""

from datetime import datetime, timezone

from workforce_intelligence.baseline.builder import METRICS
from workforce_intelligence.insights.generator import (
    build_presentation,
    render_digest_email,
    render_email,
)

OCCURRED = datetime(2026, 8, 15, 9, 10, tzinfo=timezone.utc)
DETECTED = datetime(2026, 8, 16, 2, 0, tzinfo=timezone.utc)

_BANNED_WORDS = (
    "fraud",
    "guilty",
    "intentional",
    "lazy",
    "suspicious",
    "poor performance",
    "misconduct",
)


def _presentation(**overrides) -> dict:
    kwargs = dict(
        metric="break_duration_minutes",
        observed_value=81.0,
        self_mean=32.0,
        self_std=8.0,
        self_z=6.1,
        self_n=24,
        peer_mean=35.0,
        peer_std=10.0,
        peer_z=4.6,
        peer_n=120,
        severity="high",
        occurred_at=OCCURRED,
        detected_at=DETECTED,
    )
    kwargs.update(overrides)
    return build_presentation(**kwargs)


def test_presentation_answers_the_four_questions():
    p = _presentation()
    assert p["title"] == "Unusual Break Duration"
    assert "1h 21m" in p["summary"] and "32m" in p["summary"]  # WHAT happened
    assert "differs significantly" in p["explanation"]  # WHY flagged
    assert p["evidence"]["current"] and p["evidence"]["baseline"]  # WHAT evidence
    assert any(a["action"] == "mark_reviewed" for a in p["recommended_action"])  # WHAT next


def test_presentation_evidence_has_no_internal_field_names():
    p = _presentation()
    evidence_text = " ".join(str(v) for v in p["evidence"].values())
    assert "z_score" not in evidence_text.lower()
    assert "self_z" not in evidence_text
    # z-scores live only under `technical`, not in the primary evidence view.
    assert "self_z" not in p["evidence"]
    assert p["technical"]["self_z"] == 6.1


def test_presentation_historical_observations_traceable_to_self_n():
    p = _presentation(self_n=24)
    assert p["evidence"]["historical_observations"] == 24


def test_presentation_missing_self_n_does_not_crash():
    p = _presentation(self_n=None, peer_n=None)
    assert p["evidence"]["historical_observations"] is None
    assert p["technical"]["peer_n"] is None


def test_presentation_degenerate_zero_variance_self_z_none():
    p = _presentation(
        metric="geofence_exit_count",
        observed_value=3.0,
        self_mean=0.0,
        self_std=0.0,
        self_z=None,
        self_n=15,
        severity="high",
    )
    assert p["title"] == "Unusual Number of Site Exits"
    assert "never varied" in p["explanation"]
    assert p["evidence"]["difference"]  # doesn't crash formatting a None-z difference


def test_every_metric_has_a_title_and_detection_type():
    for metric in METRICS:
        p = _presentation(metric=metric)
        assert p["title"]
        assert p["evidence"]["detection_type"]


def test_neutral_wording_across_all_metrics_and_branches():
    haystacks = []
    for metric in METRICS:
        for self_z in (None, 6.1):
            p = _presentation(metric=metric, self_z=self_z)
            haystacks.append(p["title"])
            haystacks.append(p["summary"])
            haystacks.append(p["explanation"])
            haystacks.append(str(p["evidence"]))
    blob = " ".join(haystacks).lower()
    for banned in _BANNED_WORDS:
        assert banned not in blob


def test_render_email_omits_technical_fields():
    p = _presentation()
    subject, body = render_email(p, employee_name="Ahmed", deep_link="https://app/x")
    assert "Ahmed" in subject or "Break Duration" in subject
    assert "Ahmed" in body
    assert "https://app/x" in body
    assert "z-score" not in body.lower()
    assert "self_z" not in body
    assert "anomaly indicator for review, not a conclusion" in body


def test_render_digest_email_bundles_multiple_presentations():
    presentations = [_presentation(metric=m) for m in ("break_count", "geofence_exit_count")]
    subject, body = render_digest_email(presentations, deep_link="https://app/wi")
    assert "2" in subject
    for p in presentations:
        assert p["title"] in body
    assert "https://app/wi" in body
