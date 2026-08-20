"""Detection-accuracy evaluation: z-score detector vs a naive fixed-rule
baseline, scored on a labeled synthetic corpus.

Not a pytest test (no assertions) — a standalone report generator, run
manually:

    ai/.venv/Scripts/python.exe -m workforce_intelligence.scripts.evaluate_detection_accuracy

Ground truth: PLAN.md's generator (synthetic/generator.py) labels each
generated row with the exact anomaly it injected. This script generates a
labeled corpus, builds a self-baseline from it (Module 2's own T9 exclusion
keeps the baseline clean automatically), scores every session with both the
z-score detector (Module 3) and a fixed-rule heuristic, and reports
precision/recall/F1 per anomaly type for each.

Known-in-advance limitation this script exists to surface with real numbers,
not just prose: missed_checkout has no metric in METRICS that observes it
(work_duration_minutes is skipped entirely when check_out_at is None, and
there is no session that ever happened to score a checkout position
against) — so recall for that type is expected to be ~0 for the z-score
detector. That is a real, still-open detection gap, not a scoring bug.

far_checkout now DOES have coverage, via the checkout_distance_from_checkin_km
metric (added to close this exact gap — see baseline/builder.py and
detection/detector.py). This script computes that distance itself with a
small private haversine below, since it runs standalone in ai/'s own venv
with no import path to backend/app/core/geo.py's canonical implementation —
the production path (backend/app/services/workforce_intelligence_service.py)
uses that canonical implementation instead; this is not a second production
distance formula, just eval-harness scaffolding.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date

from ..baseline.builder import AttendanceRecord, BreakRecord, compute_metrics
from ..detection.detector import Z_SCORE_THRESHOLD, detect_for_employee
from ..synthetic.generator import AnomalyConfig, EmployeeProfile, generate

HOME_LAT = 36.8065
HOME_LNG = 10.1815
SEED = 2026
DATE_START = date(2024, 1, 1)
DATE_END = date(2024, 12, 31)  # 1 year -> ~260 workdays, well above MIN_HISTORY_WORKDAYS

# Every type at a real, nonzero rate so each gets enough occurrences to score.
ANOMALY_RATES = {
    "late_arrival": 0.08,
    "short_shift": 0.08,
    "far_checkout": 0.05,
    "missed_checkout": 0.02,  # capped to at most 1 per employee by the generator itself
    "long_break": 0.08,
    "excessive_geofence_exits": 0.05,
}

# Which anomaly type SHOULD trip which detector metric, per the schema each
# type actually perturbs (see synthetic/generator.py _build_session). This is
# the evaluation's ground-truth mapping, not something the detector itself
# encodes.
ANOMALY_TO_METRIC = {
    "late_arrival": "checkin_time_of_day_minutes",
    "short_shift": "work_duration_minutes",
    "far_checkout": "checkout_distance_from_checkin_km",
    "missed_checkout": None,  # work_duration_minutes is skipped when check_out_at is None
    "long_break": "break_duration_minutes",
    "excessive_geofence_exits": "geofence_exit_count",
}

# Naive fixed-rule baseline: same threshold for every employee, no
# personalization. Values are deliberately plain "common sense" cutoffs a
# non-statistical rule-based system would ship with.
NAIVE_RULES = {
    "checkin_time_of_day_minutes": lambda v: v > 9 * 60 + 30,  # after 09:30
    "work_duration_minutes": lambda v: v < 6 * 60,  # under 6h
    "break_duration_minutes": lambda v: v > 60,  # over 1h
    "geofence_exit_count": lambda v: v >= 2,
    "checkout_distance_from_checkin_km": lambda v: v > 5.0,  # >5km from check-in
}


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Eval-harness-only distance formula — see module docstring for why this
    doesn't reuse backend/app/core/geo.py's canonical implementation."""
    r_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r_km * math.asin(math.sqrt(a))


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else None

    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else None

    def f1(self) -> float | None:
        p, r = self.precision(), self.recall()
        if not p or not r or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)


def _build_records(sessions, run_id) -> list[AttendanceRecord]:
    records = []
    for s in sessions:
        checkout_distance_from_checkin_km = None
        if s.check_out_latitude is not None and s.check_out_longitude is not None:
            checkout_distance_from_checkin_km = _haversine_km(
                s.check_in_latitude, s.check_in_longitude, s.check_out_latitude, s.check_out_longitude
            )
        records.append(
            AttendanceRecord(
                employee_id=s.employee_id,
                check_in_at=s.check_in_at,
                check_out_at=s.check_out_at,
                synthetic_anomaly_type=s.synthetic_anomaly_type,
                checkout_distance_from_checkin_km=checkout_distance_from_checkin_km,
                breaks=[
                    BreakRecord(
                        duration_minutes=(b.break_end_at - b.break_start_at).total_seconds() / 60,
                        synthetic_anomaly_type=b.synthetic_anomaly_type,
                    )
                    for b in s.breaks
                    if b.break_end_at is not None
                ],
                geofence_exit_count=sum(1 for e in s.geofence_events if e.event_type == "exit"),
                geofence_exit_count_anomalous=any(
                    e.synthetic_anomaly_type == "excessive_geofence_exits"
                    for e in s.geofence_events
                ),
                is_synthetic=True,
                synthetic_run_id=run_id,
                attendance_id=uuid.uuid4(),
            )
        )
    return records


def _naive_flags(records: list[AttendanceRecord]) -> set[tuple[uuid.UUID, str]]:
    """Returns {(attendance_id, metric)} pairs the naive fixed-rule baseline
    would flag — same granularity as the z-score detector's flags, so the two
    can be compared metric-for-metric against the same ground truth."""
    flags: set[tuple[uuid.UUID, str]] = set()
    for r in records:
        from ..baseline.builder import minutes_of_day

        checkin_val = minutes_of_day(r.check_in_at)
        if NAIVE_RULES["checkin_time_of_day_minutes"](checkin_val):
            flags.add((r.attendance_id, "checkin_time_of_day_minutes"))
        if r.check_out_at is not None:
            work_val = (r.check_out_at - r.check_in_at).total_seconds() / 60
            if NAIVE_RULES["work_duration_minutes"](work_val):
                flags.add((r.attendance_id, "work_duration_minutes"))
        if NAIVE_RULES["geofence_exit_count"](float(r.geofence_exit_count)):
            flags.add((r.attendance_id, "geofence_exit_count"))
        if r.checkout_distance_from_checkin_km is not None and NAIVE_RULES[
            "checkout_distance_from_checkin_km"
        ](r.checkout_distance_from_checkin_km):
            flags.add((r.attendance_id, "checkout_distance_from_checkin_km"))
        for b in r.breaks:
            if NAIVE_RULES["break_duration_minutes"](b.duration_minutes):
                flags.add((r.attendance_id, "break_duration_minutes"))
    return flags


def main() -> None:
    profile = EmployeeProfile(
        employee_id=uuid.uuid4(), hire_date=DATE_START, home_latitude=HOME_LAT, home_longitude=HOME_LNG
    )
    config = AnomalyConfig.from_dict(ANOMALY_RATES)
    result = generate([profile], DATE_START, DATE_END, config, seed=SEED)
    run_id = uuid.uuid4()
    records = _build_records(result.sessions, run_id)

    self_metrics = compute_metrics(records)
    # Single-employee run: no independent peer pool exists, and peer stats
    # don't gate emission (detector.py docstring) -- reuse self_metrics so
    # peer_z is computed but never the deciding factor.
    peer_metrics = self_metrics

    zscore_flags = detect_for_employee(records, self_metrics, peer_metrics, threshold=Z_SCORE_THRESHOLD)
    zscore_flag_set = {(f.attendance_id, f.metric) for f in zscore_flags}
    naive_flag_set = _naive_flags(records)

    print(f"Corpus: {len(records)} sessions, seed={SEED}, range={DATE_START}..{DATE_END}")
    print(f"Injected anomaly counts: {result.anomaly_counts}")
    print(
        f"Baseline sample sizes (n): "
        + ", ".join(f"{m}={self_metrics[m].n}" for m in self_metrics)
    )
    print()

    for detector_name, flag_set in (("z-score (Module 3)", zscore_flag_set), ("naive fixed-rule", naive_flag_set)):
        print(f"=== {detector_name} ===")
        overall = Counts()
        for anomaly_type, metric in ANOMALY_TO_METRIC.items():
            c = Counts()
            for r in records:
                # Ground truth: is THIS record positive for THIS anomaly type,
                # at the granularity the metric actually measures? Each
                # generated session carries at most one break, so a
                # session-level (attendance_id, metric) flag lookup is safe
                # even for the break_duration_minutes metric here.
                if metric == "break_duration_minutes":
                    if not r.breaks:
                        continue
                    is_positive = r.breaks[0].synthetic_anomaly_type == anomaly_type
                elif metric == "geofence_exit_count":
                    is_positive = anomaly_type == "excessive_geofence_exits" and r.geofence_exit_count_anomalous
                elif metric is not None:
                    is_positive = r.synthetic_anomaly_type == anomaly_type
                else:
                    # No metric observes this anomaly type at all -> can only
                    # ever be a missed detection (FN), never a TP or FP.
                    if r.synthetic_anomaly_type == anomaly_type:
                        c.fn += 1
                        overall.fn += 1
                    continue
                is_flagged = (r.attendance_id, metric) in flag_set
                _score(c, is_positive, is_flagged)
            for k in ("tp", "fp", "fn"):
                setattr(overall, k, getattr(overall, k) + getattr(c, k))
            print(
                f"  {anomaly_type:28s} metric={str(metric):28s} "
                f"tp={c.tp:4d} fp={c.fp:4d} fn={c.fn:4d} "
                f"precision={_fmt(c.precision())} recall={_fmt(c.recall())} f1={_fmt(c.f1())}"
            )
        print(
            f"  {'OVERALL':28s} {'':28s} "
            f"tp={overall.tp:4d} fp={overall.fp:4d} fn={overall.fn:4d} "
            f"precision={_fmt(overall.precision())} recall={_fmt(overall.recall())} f1={_fmt(overall.f1())}"
        )
        print()


def _score(c: Counts, is_positive: bool, is_flagged: bool) -> None:
    if is_positive and is_flagged:
        c.tp += 1
    elif is_flagged and not is_positive:
        c.fp += 1
    elif is_positive and not is_flagged:
        c.fn += 1


def _fmt(v: float | None) -> str:
    return f"{v:.3f}" if v is not None else "n/a"


if __name__ == "__main__":
    main()
