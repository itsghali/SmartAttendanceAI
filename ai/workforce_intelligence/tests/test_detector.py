import uuid
from datetime import datetime, timedelta, timezone

import pytest

from workforce_intelligence.baseline.builder import BreakRecord, AttendanceRecord, MetricStats
from workforce_intelligence.detection.detector import (
    MIN_METRIC_N,
    Z_SCORE_HIGH_THRESHOLD,
    Z_SCORE_THRESHOLD,
    detect_for_employee,
)

BASE_DAY = datetime(2026, 1, 5, 8, 30, tzinfo=timezone.utc)  # Monday, 08:30 check-in
EMPLOYEE_ID = uuid.uuid4()


def _session(
    day_offset: int,
    checkin_hour: int = 8,
    checkin_minute: int = 30,
    work_minutes: float | None = 480,
    breaks: list[BreakRecord] | None = None,
    exit_count: int = 0,
    is_synthetic: bool = True,
    synthetic_run_id: uuid.UUID | None = None,
    synthetic_anomaly_type: str | None = None,
    attendance_id: uuid.UUID | None = None,
    checkout_distance_from_checkin_km: float | None = None,
) -> AttendanceRecord:
    check_in = BASE_DAY.replace(hour=checkin_hour, minute=checkin_minute) + timedelta(
        days=day_offset
    )
    check_out = check_in + timedelta(minutes=work_minutes) if work_minutes is not None else None
    return AttendanceRecord(
        employee_id=EMPLOYEE_ID,
        check_in_at=check_in,
        check_out_at=check_out,
        synthetic_anomaly_type=synthetic_anomaly_type,
        breaks=breaks or [],
        geofence_exit_count=exit_count,
        is_synthetic=is_synthetic,
        synthetic_run_id=synthetic_run_id,
        attendance_id=attendance_id or uuid.uuid4(),
        checkout_distance_from_checkin_km=checkout_distance_from_checkin_km,
    )


def _flat_self_metrics(
    checkin_mean=510.0, checkin_std=10.0, checkin_n=40,
    work_mean=480.0, work_std=15.0, work_n=40,
    break_dur_mean=30.0, break_dur_std=5.0, break_dur_n=40,
    break_count_mean=1.0, break_count_std=0.0, break_count_n=40,
    exit_mean=0.0, exit_std=0.0, exit_n=40,
    checkout_dist_mean=1.0, checkout_dist_std=0.5, checkout_dist_n=40,
) -> dict[str, MetricStats]:
    return {
        "checkin_time_of_day_minutes": MetricStats(checkin_mean, checkin_std, checkin_n),
        "work_duration_minutes": MetricStats(work_mean, work_std, work_n),
        "break_duration_minutes": MetricStats(break_dur_mean, break_dur_std, break_dur_n),
        "break_count": MetricStats(break_count_mean, break_count_std, break_count_n),
        "geofence_exit_count": MetricStats(exit_mean, exit_std, exit_n),
        "checkout_distance_from_checkin_km": MetricStats(
            checkout_dist_mean, checkout_dist_std, checkout_dist_n
        ),
    }


def _neutral_peer_metrics() -> dict[str, MetricStats]:
    # Same shape as self, deliberately "no signal" (std=1 avoids /0, mean far
    # from anything a test scores) so peer_z never accidentally crosses
    # threshold and confounds a self-only assertion.
    return {
        "checkin_time_of_day_minutes": MetricStats(0.0, 1.0, 100),
        "work_duration_minutes": MetricStats(0.0, 1.0, 100),
        "break_duration_minutes": MetricStats(0.0, 1.0, 100),
        "break_count": MetricStats(0.0, 1.0, 100),
        "geofence_exit_count": MetricStats(0.0, 1.0, 100),
        "checkout_distance_from_checkin_km": MetricStats(0.0, 1.0, 100),
    }


def test_flags_significant_self_deviation():
    # checkin baseline: mean 510 (08:30), std 10 -> 11:00 checkin is 660,
    # z = (660-510)/10 = 15, way past threshold.
    session = _session(0, checkin_hour=11, checkin_minute=0)
    flags = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    checkin_flags = [f for f in flags if f.metric == "checkin_time_of_day_minutes"]
    assert len(checkin_flags) == 1
    assert checkin_flags[0].self_z == pytest.approx(15.0, abs=0.01)
    assert checkin_flags[0].severity == "high"


def test_no_flag_within_threshold():
    # checkin at 08:35 -> value 515, z = (515-510)/10 = 0.5, well under threshold.
    session = _session(0, checkin_hour=8, checkin_minute=35)
    flags = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    assert [f for f in flags if f.metric == "checkin_time_of_day_minutes"] == []


def test_severity_bucketing_moderate_vs_high():
    # z = 2.6 (moderate: >= 2.5, < 3.5)
    moderate_session = _session(0, checkin_hour=8, checkin_minute=int(30 + 26))
    flags = detect_for_employee([moderate_session], _flat_self_metrics(), _neutral_peer_metrics())
    checkin_flag = next(f for f in flags if f.metric == "checkin_time_of_day_minutes")
    assert Z_SCORE_THRESHOLD <= checkin_flag.self_z < Z_SCORE_HIGH_THRESHOLD
    assert checkin_flag.severity == "moderate"


def test_degenerate_std_flags_any_mismatch_as_high():
    # break_count baseline is a constant 1 (std=0) -> a 2-break day is
    # infinitely surprising even though self_z is undefined (0 std).
    session = _session(0, breaks=[
        BreakRecord(duration_minutes=30, synthetic_anomaly_type=None),
        BreakRecord(duration_minutes=30, synthetic_anomaly_type=None),
    ])
    flags = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    break_count_flags = [f for f in flags if f.metric == "break_count"]
    assert len(break_count_flags) == 1
    assert break_count_flags[0].self_z is None
    assert break_count_flags[0].severity == "high"


def test_degenerate_std_no_flag_when_value_matches_constant():
    # break_count baseline constant 1, session also has exactly 1 break ->
    # 0/0 must not be treated as a flag.
    session = _session(0, breaks=[BreakRecord(duration_minutes=30, synthetic_anomaly_type=None)])
    flags = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    assert [f for f in flags if f.metric == "break_count"] == []


def test_min_metric_n_gate_skips_low_sample_metric():
    self_metrics = _flat_self_metrics(work_n=MIN_METRIC_N - 1)
    # work_minutes=700 deviates hugely from mean=480/std=15 (z~14.7) -- would
    # flag if scored, so this actually exercises the n-gate, not just an
    # absence of deviation.
    session = _session(0, checkin_hour=11, work_minutes=700)
    flags = detect_for_employee([session], self_metrics, _neutral_peer_metrics())
    assert [f for f in flags if f.metric == "work_duration_minutes"] == []
    # checkin_time_of_day_minutes still has n=40, unaffected by the gate.
    assert any(f.metric == "checkin_time_of_day_minutes" for f in flags)


def test_far_checkout_flags_significant_distance_deviation():
    # self baseline: mean 1.0km, std 0.5km -> a 12km checkout is z=22, way
    # past threshold.
    session = _session(0, checkout_distance_from_checkin_km=12.0)
    flags = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    dist_flags = [f for f in flags if f.metric == "checkout_distance_from_checkin_km"]
    assert len(dist_flags) == 1
    assert dist_flags[0].severity == "high"
    assert dist_flags[0].occurred_at == session.check_out_at


def test_none_checkout_distance_is_never_scored():
    # No checkout coordinates (e.g. missed_checkout, or an ordinary session
    # missing GPS data) -> metric is skipped entirely, not flagged as a
    # deviation and no KeyError from a missing self_metrics entry.
    session = _session(0, checkout_distance_from_checkin_km=None)
    flags = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    assert [f for f in flags if f.metric == "checkout_distance_from_checkin_km"] == []


def test_break_level_flag_anchors_to_parent_session_attendance_id():
    session_id = uuid.uuid4()
    session = _session(
        0,
        attendance_id=session_id,
        breaks=[BreakRecord(duration_minutes=180, synthetic_anomaly_type=None)],
    )
    flags = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    break_flags = [f for f in flags if f.metric == "break_duration_minutes"]
    assert len(break_flags) == 1
    assert break_flags[0].attendance_id == session_id


def test_peer_z_stored_as_context_does_not_suppress_self_deviation():
    # Peer baseline set to make peer_z ALSO extreme in the same direction
    # (simulating "everyone shifted") -- flag still fires, since peer
    # context doesn't gate emission this pass (see detector.py docstring).
    peer_metrics = _flat_self_metrics(checkin_mean=655.0, checkin_std=1.0)
    session = _session(0, checkin_hour=11, checkin_minute=0)
    flags = detect_for_employee([session], _flat_self_metrics(), peer_metrics)
    checkin_flag = next(f for f in flags if f.metric == "checkin_time_of_day_minutes")
    assert checkin_flag.peer_z is not None
    assert abs(checkin_flag.peer_z) < 6  # peer also finds it close to normal-ish
    assert checkin_flag.self_z == pytest.approx(15.0, abs=0.01)  # still flagged on self


def test_synthetic_provenance_passthrough():
    run_id = uuid.uuid4()
    session = _session(
        0, checkin_hour=11, is_synthetic=True, synthetic_run_id=run_id,
        synthetic_anomaly_type="late_arrival",
    )
    flags = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    checkin_flag = next(f for f in flags if f.metric == "checkin_time_of_day_minutes")
    assert checkin_flag.is_synthetic is True
    assert checkin_flag.synthetic_run_id == run_id
    assert checkin_flag.synthetic_anomaly_type == "late_arrival"


def test_missing_attendance_id_raises():
    session = _session(0, checkin_hour=11)
    object.__setattr__(session, "attendance_id", None)
    with pytest.raises(ValueError):
        detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())


def test_deterministic_pure_function_same_input_same_output():
    session = _session(0, checkin_hour=11)
    a = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    b = detect_for_employee([session], _flat_self_metrics(), _neutral_peer_metrics())
    assert [(f.metric, f.self_z) for f in a] == [(f.metric, f.self_z) for f in b]
