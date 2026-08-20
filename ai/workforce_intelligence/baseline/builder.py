"""Per-employee + peer-group baseline builder (Module 2).

Pure, DB-agnostic (mirrors ai/workforce_intelligence/synthetic/generator.py's
style) — the caller (backend/app/services/workforce_intelligence_service.py)
queries Attendance/BreakPeriod/GeofenceEvent (both real AND synthetic rows —
this is the one legitimate consumer that must NOT apply the T0/T1
is_synthetic=false filter, since synthetic data is currently the only
bootstrap history) and assembles AttendanceRecord inputs; this module only
does the statistics.

Thresholds (PLAN.md Step 0E, decided this sprint, not yet re-validated
against real data — see EmployeeBaseline's own docstring):
- MIN_HISTORY_WORKDAYS = 40 (~8 weeks) clean workdays before a self-baseline
  is trustworthy enough to write.
- MIN_DEPARTMENT_SIZE = 20 distinct employees before a peer-group uses its
  own department instead of falling back to company-wide.

T9 (anomaly exclusion): a metric's data points are pulled ONLY from rows
that are not themselves anomaly-labeled. A session-level anomaly
(late_arrival/short_shift/far_checkout/missed_checkout) excludes that whole
session's check-in-time/work-duration/break-count contribution; a
break-level anomaly (long_break) excludes only that break's duration; a
geofence-level anomaly (excessive_geofence_exits) excludes only that
session's exit-count contribution. The generator never combines more than
one anomaly type per session, but this module does not assume that — each
metric checks its own governing flag(s) independently, so it stays correct
even against hand-authored or future non-generator data.
"""

from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from ..exceptions import InsufficientHistoryError

MIN_HISTORY_WORKDAYS = 40
MIN_DEPARTMENT_SIZE = 20

METRICS = (
    "checkin_time_of_day_minutes",
    "work_duration_minutes",
    "break_duration_minutes",
    "break_count",
    "geofence_exit_count",
    "checkout_distance_from_checkin_km",
)


@dataclass(frozen=True)
class BreakRecord:
    duration_minutes: float
    synthetic_anomaly_type: str | None


@dataclass(frozen=True)
class AttendanceRecord:
    employee_id: uuid.UUID
    check_in_at: datetime
    check_out_at: datetime | None
    synthetic_anomaly_type: str | None
    breaks: list[BreakRecord] = field(default_factory=list)
    geofence_exit_count: int = 0
    # True if any EXIT/RETURN event on this session carries an anomaly label
    # (excessive_geofence_exits) — governs the geofence_exit_count metric
    # only, independent of synthetic_anomaly_type on the session itself.
    geofence_exit_count_anomalous: bool = False
    # Provenance passthrough for Module 3 (detection/detector.py) — the
    # baseline builder itself never filters on this (see module docstring),
    # it just needs to carry the flag so a detector-produced
    # EmployeeDeviationFlag can be tagged is_synthetic/synthetic_run_id too
    # (PLAN.md T0/T1 precedent applied to Module 3's own output table).
    is_synthetic: bool = False
    synthetic_run_id: uuid.UUID | None = None
    attendance_id: uuid.UUID | None = None
    # Pre-computed by the caller (backend/app/services/workforce_intelligence_
    # service.py, via app.core.geo.haversine_distance_meters — the one
    # haversine implementation in the repo, not duplicated here to keep this
    # package pure/DB-agnostic). None when either endpoint's coordinates are
    # missing (manual entries, open sessions) — never coerced to 0.0, which
    # would read as "checked out exactly where they checked in."
    checkout_distance_from_checkin_km: float | None = None


@dataclass(frozen=True)
class MetricStats:
    mean: float | None
    std: float | None
    n: int

    def to_dict(self) -> dict:
        return {"mean": self.mean, "std": self.std, "n": self.n}


@dataclass(frozen=True)
class EmployeeSelfBaseline:
    employee_id: uuid.UUID
    metrics: dict[str, MetricStats]


@dataclass(frozen=True)
class PeerGroupBaseline:
    source: str  # "department" | "company_wide"
    department_id: uuid.UUID | None
    pool_size: int
    metrics: dict[str, MetricStats]


# Public (not module-private): ai/workforce_intelligence/detection/detector.py
# reuses this exact formula so a session's checkin_time_of_day_minutes is
# computed identically whether it's feeding the baseline or being scored
# against one — the whole-second truncation (dt.second, not
# dt.microsecond-precise) is a real, if immaterial, quirk of this formula
# (see AI-CHANGELOG.md's Sprint 6 spot-check entry) and must stay identical
# on both sides, not silently drift if duplicated.
def minutes_of_day(dt: datetime) -> float:
    return dt.hour * 60 + dt.minute + dt.second / 60


def _stats(values: list[float]) -> MetricStats:
    n = len(values)
    if n == 0:
        return MetricStats(mean=None, std=None, n=0)
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if n > 1 else 0.0
    return MetricStats(mean=mean, std=std, n=n)


def compute_metrics(sessions: list[AttendanceRecord]) -> dict[str, MetricStats]:
    """Pure aggregation over a pool of sessions (one employee's own history
    for a self-baseline, or many employees' pooled history for a peer-group
    baseline) into per-metric mean/std/n, honoring T9 exclusion."""
    checkin_minutes: list[float] = []
    work_minutes: list[float] = []
    break_minutes: list[float] = []
    break_counts: list[float] = []
    exit_counts: list[float] = []
    checkout_distances_km: list[float] = []

    for s in sessions:
        session_clean = s.synthetic_anomaly_type is None
        if session_clean:
            checkin_minutes.append(minutes_of_day(s.check_in_at))
            if s.check_out_at is not None:
                work_minutes.append((s.check_out_at - s.check_in_at).total_seconds() / 60)
            break_counts.append(float(len(s.breaks)))
            # No separate T9 flag needed beyond session_clean: far_checkout is
            # a session-level anomaly (already gated by session_clean above),
            # and missed_checkout sessions have no checkout coordinates at all
            # so checkout_distance_from_checkin_km is already None for them —
            # the `is not None` guard excludes them without a second check.
            if s.checkout_distance_from_checkin_km is not None:
                checkout_distances_km.append(s.checkout_distance_from_checkin_km)
        for b in s.breaks:
            if b.synthetic_anomaly_type is None:
                break_minutes.append(b.duration_minutes)
        if not s.geofence_exit_count_anomalous:
            exit_counts.append(float(s.geofence_exit_count))

    return {
        "checkin_time_of_day_minutes": _stats(checkin_minutes),
        "work_duration_minutes": _stats(work_minutes),
        "break_duration_minutes": _stats(break_minutes),
        "break_count": _stats(break_counts),
        "checkout_distance_from_checkin_km": _stats(checkout_distances_km),
        "geofence_exit_count": _stats(exit_counts),
    }


def build_for_employee(
    employee_id: uuid.UUID,
    sessions: list[AttendanceRecord],
    min_history_workdays: int = MIN_HISTORY_WORKDAYS,
) -> EmployeeSelfBaseline:
    metrics = compute_metrics(sessions)
    # checkin_time_of_day_minutes has one data point per CLEAN session and no
    # extra eligibility condition (unlike work_duration, which additionally
    # needs a check-out) — it's the most complete signal of "how many clean
    # workdays of history do we actually have."
    clean_workdays = metrics["checkin_time_of_day_minutes"].n
    if clean_workdays < min_history_workdays:
        raise InsufficientHistoryError(
            f"employee {employee_id} has {clean_workdays} clean workdays of history, "
            f"needs {min_history_workdays}"
        )
    return EmployeeSelfBaseline(employee_id=employee_id, metrics=metrics)


def build_peer_group(
    department_id: uuid.UUID | None,
    department_pool: dict[uuid.UUID, list[AttendanceRecord]],
    company_wide_pool: dict[uuid.UUID, list[AttendanceRecord]],
    min_department_size: int = MIN_DEPARTMENT_SIZE,
) -> PeerGroupBaseline:
    """Not an error path (PLAN.md Step 0E) — a department with too few
    employees (or no department at all, department_id is None) falls back to
    the company-wide pool instead of dividing by near-zero variance."""
    if department_id is not None and len(department_pool) >= min_department_size:
        pool = department_pool
        source = "department"
        resolved_department_id = department_id
    else:
        pool = company_wide_pool
        source = "company_wide"
        resolved_department_id = None

    all_sessions = [s for sessions in pool.values() for s in sessions]
    metrics = compute_metrics(all_sessions)
    return PeerGroupBaseline(
        source=source,
        department_id=resolved_department_id,
        pool_size=len(pool),
        metrics=metrics,
    )


def to_metric_stats_json(
    self_baseline: EmployeeSelfBaseline, peer_baseline: PeerGroupBaseline
) -> dict:
    """Assembles the combined {"self": ..., "peer": ...} per-metric shape
    documented on backend/app/models/employee_baseline.py's
    EmployeeBaseline.metric_stats docstring."""
    result = {}
    for metric in METRICS:
        result[metric] = {
            "self": self_baseline.metrics[metric].to_dict(),
            "peer": {
                **peer_baseline.metrics[metric].to_dict(),
                "source": peer_baseline.source,
                "department_id": str(peer_baseline.department_id)
                if peer_baseline.department_id
                else None,
            },
        }
    return result
