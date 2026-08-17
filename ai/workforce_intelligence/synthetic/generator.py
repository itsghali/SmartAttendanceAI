"""Synthetic historical attendance/break/geofence data generator (Module 1).

Pure, DB-agnostic (mirrors ai/fraud_detection's pure-function style) — takes
plain EmployeeProfile inputs and returns plain dataclass row specs; the
caller (backend/app/services/workforce_intelligence_service.py) is
responsible for turning these into actual ORM rows via the bulk-insert
repository methods, inside one transaction (PLAN.md T2).

Anomaly design (PLAN.md T9): each generated work-day gets AT MOST ONE
controlled anomaly, drawn from `ANOMALY_TYPES` at the configured per-type
rate. The label is written on whichever row is actually anomalous — the
Attendance row for session-level anomalies (late_arrival, short_shift,
far_checkout, missed_checkout), the BreakPeriod row for long_break, the
GeofenceEvent rows for excessive_geofence_exits — never on rows that are
otherwise normal, so a baseline builder (Module 2) can exclude exactly the
anomalous rows and nothing else when computing "normal" stats.

Referential/temporal consistency (PLAN.md T12): every session is built
top-down (check-in time first, then work duration bounds check-out, breaks
are clamped inside [check_in_at, check_out_at), geofence EXIT/RETURN pairs
are offset from check_in_at in order) so nothing downstream has to repair
row ordering after the fact.

Open-session collision guard (PLAN.md T13): `missed_checkout` (the only
anomaly that leaves check_out_at NULL) is only ever considered for an
employee's LAST eligible day in the requested range, and only when the
caller says that employee has no real open session already — see
`employees_with_open_session`. This bounds each employee to at most one
open synthetic row across the whole batch, which is what
uq_attendance_one_open_session requires regardless of is_synthetic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

import numpy as np

from ..exceptions import SyntheticConfigError

DEFAULT_WORK_DAYS = frozenset({0, 1, 2, 3, 4})  # Mon-Fri

# Session-level: the Attendance row itself is the anomalous one.
SESSION_LEVEL_ANOMALIES = ("late_arrival", "short_shift", "far_checkout", "missed_checkout")
# Sub-row level: the anomaly lives on a BreakPeriod / GeofenceEvent row.
BREAK_LEVEL_ANOMALIES = ("long_break",)
GEOFENCE_LEVEL_ANOMALIES = ("excessive_geofence_exits",)
ANOMALY_TYPES = SESSION_LEVEL_ANOMALIES + BREAK_LEVEL_ANOMALIES + GEOFENCE_LEVEL_ANOMALIES

_MAX_ANOMALY_RATE = 0.5


@dataclass(frozen=True)
class AnomalyConfig:
    rates: dict[str, float]

    @classmethod
    def from_dict(cls, raw: dict | None) -> "AnomalyConfig":
        raw = raw or {}
        if not isinstance(raw, dict):
            raise SyntheticConfigError("anomaly_config must be a JSON object")
        rates = {t: 0.0 for t in ANOMALY_TYPES}
        for key, value in raw.items():
            if key not in ANOMALY_TYPES:
                raise SyntheticConfigError(
                    f"unknown anomaly type {key!r} - must be one of {ANOMALY_TYPES}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SyntheticConfigError(f"anomaly rate for {key!r} must be a number")
            if not (0.0 <= value <= _MAX_ANOMALY_RATE):
                raise SyntheticConfigError(
                    f"anomaly rate for {key!r} must be within [0, {_MAX_ANOMALY_RATE}], got {value}"
                )
            rates[key] = float(value)
        return cls(rates=rates)


@dataclass(frozen=True)
class EmployeeProfile:
    """Caller-supplied, real facts about the employee — never randomized.
    home_latitude/home_longitude come from the employee's actual eligible
    geofence, not a synthetic value."""

    employee_id: uuid.UUID
    hire_date: date
    home_latitude: float
    home_longitude: float


@dataclass(frozen=True)
class _BehaviorProfile:
    """Per-employee "usual" behavior, drawn from the RNG (T6) — not caller
    input, so the whole corpus is reproducible from `seed` alone. Centering
    variation per-employee (not globally identical) is what makes Module 2's
    per-employee baselines meaningful."""

    usual_checkin_minute: int
    usual_work_minutes: int
    usual_break_minutes: int


def _draw_behavior_profile(rng: np.random.Generator) -> _BehaviorProfile:
    return _BehaviorProfile(
        usual_checkin_minute=int(rng.integers(7 * 60, 9 * 60 + 1)),
        usual_work_minutes=int(rng.integers(7 * 60, 9 * 60 + 1)),
        usual_break_minutes=int(rng.integers(20, 46)),
    )


@dataclass
class SyntheticBreakRow:
    break_start_at: datetime
    break_end_at: datetime | None
    start_latitude: float
    start_longitude: float
    end_latitude: float | None
    end_longitude: float | None
    synthetic_anomaly_type: str | None


@dataclass
class SyntheticGeofenceEventRow:
    event_type: str  # "enter" | "exit" | "return"
    occurred_at: datetime
    latitude: float
    longitude: float
    synthetic_anomaly_type: str | None


@dataclass
class SyntheticAttendanceRow:
    employee_id: uuid.UUID
    attendance_date: date
    check_in_at: datetime
    check_in_latitude: float
    check_in_longitude: float
    check_out_at: datetime | None
    check_out_latitude: float | None
    check_out_longitude: float | None
    status: str  # AttendanceStatus.value ("present" | "late")
    synthetic_anomaly_type: str | None
    breaks: list[SyntheticBreakRow] = field(default_factory=list)
    geofence_events: list[SyntheticGeofenceEventRow] = field(default_factory=list)


@dataclass
class GenerationResult:
    sessions: list[SyntheticAttendanceRow]
    anomaly_counts: dict[str, int]


def _pick_anomaly(rng: np.random.Generator, config: AnomalyConfig, allow_missed_checkout: bool) -> str | None:
    types = [t for t in ANOMALY_TYPES if t != "missed_checkout" or allow_missed_checkout]
    draw = float(rng.random())
    cumulative = 0.0
    for anomaly_type in types:
        cumulative += config.rates[anomaly_type]
        if draw < cumulative:
            return anomaly_type
    return None


def _jitter(rng: np.random.Generator, scale: float = 0.0005) -> float:
    # ~0.0005 degrees latitude/longitude is on the order of 50m — realistic
    # GPS noise around a fixed work location, not a meaningfully different
    # place.
    return float(rng.normal(0.0, scale))


def _build_session(
    profile: EmployeeProfile,
    behavior: _BehaviorProfile,
    day: date,
    anomaly_type: str | None,
    rng: np.random.Generator,
) -> SyntheticAttendanceRow:
    checkin_minute = max(0.0, behavior.usual_checkin_minute + float(rng.normal(0.0, 10.0)))
    if anomaly_type == "late_arrival":
        checkin_minute += float(rng.uniform(60.0, 180.0))
    check_in_at = datetime.combine(day, time(0, 0), tzinfo=timezone.utc) + timedelta(
        minutes=checkin_minute
    )

    work_minutes = max(30.0, behavior.usual_work_minutes + float(rng.normal(0.0, 20.0)))
    if anomaly_type == "short_shift":
        work_minutes = max(30.0, work_minutes * float(rng.uniform(0.3, 0.5)))

    check_out_at = None if anomaly_type == "missed_checkout" else check_in_at + timedelta(
        minutes=work_minutes
    )

    check_in_lat = profile.home_latitude + _jitter(rng)
    check_in_lng = profile.home_longitude + _jitter(rng)

    check_out_lat: float | None = None
    check_out_lng: float | None = None
    if check_out_at is not None:
        if anomaly_type == "far_checkout":
            # ~5-15km away — far enough to be physically implausible to
            # travel in a normal work-adjacent elapsed time, without being
            # so extreme it reads as a data-entry typo instead of travel.
            sign_lat = 1.0 if rng.random() < 0.5 else -1.0
            sign_lng = 1.0 if rng.random() < 0.5 else -1.0
            check_out_lat = profile.home_latitude + sign_lat * float(rng.uniform(0.05, 0.15))
            check_out_lng = profile.home_longitude + sign_lng * float(rng.uniform(0.05, 0.15))
        else:
            check_out_lat = profile.home_latitude + _jitter(rng)
            check_out_lng = profile.home_longitude + _jitter(rng)

    breaks: list[SyntheticBreakRow] = []
    if work_minutes > 90:
        break_minutes = max(5.0, behavior.usual_break_minutes + float(rng.normal(0.0, 5.0)))
        break_anomaly = anomaly_type if anomaly_type in BREAK_LEVEL_ANOMALIES else None
        if break_anomaly == "long_break":
            break_minutes *= float(rng.uniform(2.0, 4.0))
        break_start_at = check_in_at + timedelta(minutes=work_minutes / 2)
        break_end_at = break_start_at + timedelta(minutes=break_minutes)
        if check_out_at is not None and break_end_at >= check_out_at:
            break_end_at = check_out_at - timedelta(minutes=1)
            break_start_at = min(break_start_at, break_end_at - timedelta(minutes=1))
        breaks.append(
            SyntheticBreakRow(
                break_start_at=break_start_at,
                break_end_at=break_end_at,
                start_latitude=check_in_lat,
                start_longitude=check_in_lng,
                end_latitude=check_in_lat,
                end_longitude=check_in_lng,
                synthetic_anomaly_type=break_anomaly,
            )
        )

    geofence_events = [
        SyntheticGeofenceEventRow(
            event_type="enter",
            occurred_at=check_in_at,
            latitude=check_in_lat,
            longitude=check_in_lng,
            synthetic_anomaly_type=None,
        )
    ]
    if anomaly_type == "excessive_geofence_exits" and check_out_at is not None:
        exit_count = int(rng.integers(3, 6))
        span_seconds = max((check_out_at - check_in_at).total_seconds() - 120.0, 60.0)
        for i in range(exit_count):
            exit_at = check_in_at + timedelta(
                seconds=60 + span_seconds * (i + 1) / (exit_count + 1)
            )
            return_at = exit_at + timedelta(minutes=1)
            if check_out_at is not None and return_at >= check_out_at:
                return_at = check_out_at - timedelta(seconds=1)
            geofence_events.append(
                SyntheticGeofenceEventRow(
                    event_type="exit",
                    occurred_at=exit_at,
                    latitude=profile.home_latitude + _jitter(rng, scale=0.001),
                    longitude=profile.home_longitude + _jitter(rng, scale=0.001),
                    synthetic_anomaly_type="excessive_geofence_exits",
                )
            )
            geofence_events.append(
                SyntheticGeofenceEventRow(
                    event_type="return",
                    occurred_at=return_at,
                    latitude=check_in_lat,
                    longitude=check_in_lng,
                    synthetic_anomaly_type="excessive_geofence_exits",
                )
            )

    session_anomaly = anomaly_type if anomaly_type in SESSION_LEVEL_ANOMALIES else None
    status = "late" if anomaly_type == "late_arrival" else "present"

    return SyntheticAttendanceRow(
        employee_id=profile.employee_id,
        attendance_date=day,
        check_in_at=check_in_at,
        check_in_latitude=check_in_lat,
        check_in_longitude=check_in_lng,
        check_out_at=check_out_at,
        check_out_latitude=check_out_lat,
        check_out_longitude=check_out_lng,
        status=status,
        synthetic_anomaly_type=session_anomaly,
        breaks=breaks,
        geofence_events=geofence_events,
    )


def generate(
    profiles: list[EmployeeProfile],
    date_range_start: date,
    date_range_end: date,
    config: AnomalyConfig,
    seed: int,
    employees_with_open_session: frozenset[uuid.UUID] = frozenset(),
    work_days: frozenset[int] = DEFAULT_WORK_DAYS,
) -> GenerationResult:
    if date_range_end < date_range_start:
        raise SyntheticConfigError("date_range_end must not precede date_range_start")

    # T6: numpy.random.default_rng(seed), never the global numpy.random.seed()
    # — a shared global RNG would make two concurrent generation runs
    # non-reproducible and non-independent.
    rng = np.random.default_rng(seed)

    total_days = (date_range_end - date_range_start).days + 1
    all_dates = [date_range_start + timedelta(days=i) for i in range(total_days)]
    work_dates = [d for d in all_dates if d.weekday() in work_days]

    sessions: list[SyntheticAttendanceRow] = []
    anomaly_counts: dict[str, int] = {t: 0 for t in ANOMALY_TYPES}

    for profile in profiles:
        eligible_dates = [d for d in work_dates if d >= profile.hire_date]
        if not eligible_dates:
            continue
        behavior = _draw_behavior_profile(rng)
        last_eligible_date = eligible_dates[-1]
        can_miss_checkout = profile.employee_id not in employees_with_open_session

        for day in eligible_dates:
            allow_missed_checkout = can_miss_checkout and day == last_eligible_date
            anomaly_type = _pick_anomaly(rng, config, allow_missed_checkout)
            session = _build_session(profile, behavior, day, anomaly_type, rng)
            sessions.append(session)
            if anomaly_type is not None:
                anomaly_counts[anomaly_type] += 1

    return GenerationResult(sessions=sessions, anomaly_counts=anomaly_counts)
