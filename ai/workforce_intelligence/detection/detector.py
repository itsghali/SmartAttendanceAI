"""Deviation/anomaly detection (Module 3).

Pure, DB-agnostic (mirrors ai/workforce_intelligence/baseline/builder.py's
style) — the caller (backend/app/services/workforce_intelligence_service.py)
supplies the same AttendanceRecord pool Module 2 already builds baselines
from, plus the EmployeeBaseline's already-computed self/peer MetricStats;
this module only scores.

Method (PLAN.md's Layer-3 EUREKA extended to Module 3, re-decided at
implementation time — see AI-CHANGELOG.md's Module 3 entry for the full
reasoning): z-score against the employee's OWN baseline
(self_mean/self_std), not a fitted IsolationForest. The metric that crossed
the threshold IS the reason a flag exists, so no SHAP/explainability layer
is needed for Module 3 to be evidence-based — deferred, unstarted Module 4
still owns turning a flag into human-readable prose. This also sidesteps the
Section 2 CEO-review "SHAP degenerate-variance" GAP entirely: it only
existed because SHAP was in the picture.

Peer stats (peer_mean/peer_std) are carried onto every flag as CONTEXT for a
human reviewer — they do NOT gate whether a flag is emitted. A true
company-wide-event suppression (Candidate 2's stated purpose) needs the peer
group's CURRENT period compared against its OWN prior period; this pass only
has one peer baseline (no temporal peer history), so building a suppression
heuristic on top of it would be guessing, not detecting. Named as a real,
open limitation rather than silently shipped as a shaky "looks-random" rule.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from ..baseline.builder import AttendanceRecord, MetricStats, minutes_of_day

# z >= 2.5 is roughly the 98.8th percentile under a normal approximation —
# standard-enough UEBA behavioral-anomaly convention (CEO-phase Landscape
# Check). z >= 3.5 (~99.98th percentile) is the MODERATE/HIGH split.
# Hardcoded policy decisions, same "worth a comment explaining WHY" flag
# PLAN.md's Section 10 already raised for MIN_HISTORY_WORKDAYS/
# MIN_DEPARTMENT_SIZE — these are that same class of number.
Z_SCORE_THRESHOLD = 2.5
Z_SCORE_HIGH_THRESHOLD = 3.5

# A metric's self_mean/self_std computed from fewer than this many points is
# too noisy to score against, even if the employee already cleared the
# baseline's own MIN_HISTORY_WORKDAYS gate on checkin_time_of_day_minutes —
# work_duration/break_duration/break_count/geofence_exit_count can each
# independently have far fewer qualifying data points than that headline
# metric. Below this, the metric is skipped for detection, not flagged.
MIN_METRIC_N = 10


@dataclass(frozen=True)
class DeviationFlag:
    employee_id: uuid.UUID
    attendance_id: uuid.UUID
    metric: str
    occurred_at: datetime
    observed_value: float
    self_mean: float
    self_std: float
    self_z: float | None
    peer_mean: float
    peer_std: float
    peer_z: float | None
    severity: str  # "moderate" | "high"
    is_synthetic: bool
    synthetic_run_id: uuid.UUID | None
    synthetic_anomaly_type: str | None


def _z(value: float, mean: float, std: float) -> float | None:
    if std == 0.0:
        return None
    return (value - mean) / std


def _severity(z: float) -> str:
    return "high" if abs(z) >= Z_SCORE_HIGH_THRESHOLD else "moderate"


def _score_one(
    *,
    metric: str,
    value: float,
    occurred_at: datetime,
    session: AttendanceRecord,
    self_stats: MetricStats,
    peer_stats: MetricStats,
    threshold: float,
) -> DeviationFlag | None:
    if self_stats.n < MIN_METRIC_N or self_stats.mean is None:
        return None

    self_z = _z(value, self_stats.mean, self_stats.std)
    peer_z = (
        _z(value, peer_stats.mean, peer_stats.std)
        if peer_stats.mean is not None
        else None
    )

    if self_z is None:
        # Degenerate self-variance (e.g. a metric that's been exactly
        # constant for this employee): ANY deviation from that constant is
        # inherently significant — flag it as HIGH rather than silently
        # passing (0/0 would otherwise mean "never flag"). An exact match to
        # a zero-variance baseline is unremarkable and is not flagged.
        if value == self_stats.mean:
            return None
        severity = "high"
    elif abs(self_z) >= threshold:
        severity = _severity(self_z)
    else:
        return None

    return DeviationFlag(
        employee_id=session.employee_id,
        attendance_id=session.attendance_id,
        metric=metric,
        occurred_at=occurred_at,
        observed_value=value,
        self_mean=self_stats.mean,
        self_std=self_stats.std,
        self_z=self_z,
        peer_mean=peer_stats.mean if peer_stats.mean is not None else 0.0,
        peer_std=peer_stats.std if peer_stats.std is not None else 0.0,
        peer_z=peer_z,
        severity=severity,
        is_synthetic=session.is_synthetic,
        synthetic_run_id=session.synthetic_run_id,
        synthetic_anomaly_type=session.synthetic_anomaly_type,
    )


def detect_for_employee(
    sessions: list[AttendanceRecord],
    self_metrics: dict[str, MetricStats],
    peer_metrics: dict[str, MetricStats],
    threshold: float = Z_SCORE_THRESHOLD,
) -> list[DeviationFlag]:
    """Scores every session (and every break within it) against the
    employee's own baseline, session-level metrics per session and
    break_duration_minutes per individual break — same granularity Module
    2's own T9 anomaly-exclusion already uses. Deliberately scores EVERY
    session including anomaly-labeled ones (unlike compute_metrics, which
    excludes them when FITTING the baseline) — that's what makes the
    detection-accuracy validation test possible: a labeled-anomalous session
    should usually get flagged when scored against the clean baseline that
    excluded it."""
    flags: list[DeviationFlag] = []
    for s in sessions:
        if s.attendance_id is None:
            raise ValueError(
                "detect_for_employee requires AttendanceRecord.attendance_id to be set"
            )

        flag = _score_one(
            metric="checkin_time_of_day_minutes",
            value=minutes_of_day(s.check_in_at),
            occurred_at=s.check_in_at,
            session=s,
            self_stats=self_metrics["checkin_time_of_day_minutes"],
            peer_stats=peer_metrics["checkin_time_of_day_minutes"],
            threshold=threshold,
        )
        if flag is not None:
            flags.append(flag)

        if s.check_out_at is not None:
            flag = _score_one(
                metric="work_duration_minutes",
                value=(s.check_out_at - s.check_in_at).total_seconds() / 60,
                occurred_at=s.check_in_at,
                session=s,
                self_stats=self_metrics["work_duration_minutes"],
                peer_stats=peer_metrics["work_duration_minutes"],
                threshold=threshold,
            )
            if flag is not None:
                flags.append(flag)

        flag = _score_one(
            metric="break_count",
            value=float(len(s.breaks)),
            occurred_at=s.check_in_at,
            session=s,
            self_stats=self_metrics["break_count"],
            peer_stats=peer_metrics["break_count"],
            threshold=threshold,
        )
        if flag is not None:
            flags.append(flag)

        flag = _score_one(
            metric="geofence_exit_count",
            value=float(s.geofence_exit_count),
            occurred_at=s.check_in_at,
            session=s,
            self_stats=self_metrics["geofence_exit_count"],
            peer_stats=peer_metrics["geofence_exit_count"],
            threshold=threshold,
        )
        if flag is not None:
            flags.append(flag)

        for b in s.breaks:
            flag = _score_one(
                metric="break_duration_minutes",
                value=b.duration_minutes,
                occurred_at=s.check_in_at,
                session=s,
                self_stats=self_metrics["break_duration_minutes"],
                peer_stats=peer_metrics["break_duration_minutes"],
                threshold=threshold,
            )
            if flag is not None:
                flags.append(flag)

    return flags
