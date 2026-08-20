import uuid
from datetime import datetime, timedelta, timezone

import pytest

from workforce_intelligence.baseline.builder import (
    METRICS,
    AttendanceRecord,
    BreakRecord,
    build_for_employee,
    build_peer_group,
    compute_metrics,
    to_metric_stats_json,
)
from workforce_intelligence.exceptions import InsufficientHistoryError

BASE_DAY = datetime(2026, 1, 5, 8, 30, tzinfo=timezone.utc)  # Monday, 08:30 check-in


def _session(
    day_offset: int,
    checkin_hour: int = 8,
    checkin_minute: int = 30,
    work_minutes: float = 480,
    anomaly: str | None = None,
    breaks: list[BreakRecord] | None = None,
    exit_count: int = 0,
    exit_anomalous: bool = False,
    checkout_distance_from_checkin_km: float | None = None,
) -> AttendanceRecord:
    check_in = BASE_DAY.replace(hour=checkin_hour, minute=checkin_minute) + timedelta(
        days=day_offset
    )
    check_out = check_in + timedelta(minutes=work_minutes) if work_minutes is not None else None
    return AttendanceRecord(
        employee_id=uuid.uuid4(),
        check_in_at=check_in,
        check_out_at=check_out,
        synthetic_anomaly_type=anomaly,
        breaks=breaks or [],
        geofence_exit_count=exit_count,
        geofence_exit_count_anomalous=exit_anomalous,
        checkout_distance_from_checkin_km=checkout_distance_from_checkin_km,
    )


def _clean_sessions(n: int, employee_id=None) -> list[AttendanceRecord]:
    sessions = []
    for i in range(n):
        s = _session(
            i,
            breaks=[BreakRecord(duration_minutes=30, synthetic_anomaly_type=None)],
            checkout_distance_from_checkin_km=1.0,
        )
        if employee_id is not None:
            s = AttendanceRecord(
                employee_id=employee_id,
                check_in_at=s.check_in_at,
                check_out_at=s.check_out_at,
                synthetic_anomaly_type=s.synthetic_anomaly_type,
                breaks=s.breaks,
                geofence_exit_count=s.geofence_exit_count,
                geofence_exit_count_anomalous=s.geofence_exit_count_anomalous,
                checkout_distance_from_checkin_km=s.checkout_distance_from_checkin_km,
            )
        sessions.append(s)
    return sessions


def test_insufficient_history_raises_below_threshold():
    sessions = _clean_sessions(39)
    with pytest.raises(InsufficientHistoryError):
        build_for_employee(uuid.uuid4(), sessions, min_history_workdays=40)


def test_exactly_at_threshold_succeeds():
    sessions = _clean_sessions(40)
    baseline = build_for_employee(uuid.uuid4(), sessions, min_history_workdays=40)
    assert baseline.metrics["checkin_time_of_day_minutes"].n == 40


def test_session_level_anomaly_excludes_checkin_work_and_break_count():
    sessions = _clean_sessions(40) + [
        _session(100, checkin_hour=11, anomaly="late_arrival", breaks=[
            BreakRecord(duration_minutes=30, synthetic_anomaly_type=None)
        ])
    ]
    metrics = compute_metrics(sessions)
    # 40 clean + 1 anomalous = 41 sessions total, but the anomalous one must
    # not appear in checkin/work_duration/break_count.
    assert metrics["checkin_time_of_day_minutes"].n == 40
    assert metrics["work_duration_minutes"].n == 40
    assert metrics["break_count"].n == 40
    # The anomalous session's break itself wasn't labeled -- but per the
    # module's stated exclusion rule, break_duration is governed by the
    # BREAK's own flag, not the session's, so it still counts.
    assert metrics["break_duration_minutes"].n == 41


def test_break_level_anomaly_excludes_only_break_duration():
    clean = _clean_sessions(40)
    anomalous_break_session = _session(
        100,
        breaks=[BreakRecord(duration_minutes=180, synthetic_anomaly_type="long_break")],
    )
    metrics = compute_metrics(clean + [anomalous_break_session])
    assert metrics["checkin_time_of_day_minutes"].n == 41
    assert metrics["work_duration_minutes"].n == 41
    assert metrics["break_count"].n == 41  # the session had 1 break, that's not excluded
    assert metrics["break_duration_minutes"].n == 40  # but that break's OWN duration is


def test_geofence_level_anomaly_excludes_only_exit_count():
    clean = _clean_sessions(40)
    anomalous_exit_session = _session(100, exit_count=5, exit_anomalous=True)
    metrics = compute_metrics(clean + [anomalous_exit_session])
    assert metrics["checkin_time_of_day_minutes"].n == 41
    assert metrics["geofence_exit_count"].n == 40


def test_missed_checkout_excluded_from_work_duration_but_not_checkin():
    clean = _clean_sessions(40)
    open_session = _session(100, work_minutes=None, anomaly="missed_checkout")
    metrics = compute_metrics(clean + [open_session])
    # missed_checkout is a SESSION-level anomaly -> excluded from checkin too
    assert metrics["checkin_time_of_day_minutes"].n == 40
    assert metrics["work_duration_minutes"].n == 40


def test_far_checkout_anomaly_excluded_from_checkout_distance_metric():
    clean = _clean_sessions(40)  # each clean session contributes 1.0km
    far_checkout_session = _session(100, anomaly="far_checkout", checkout_distance_from_checkin_km=12.0)
    metrics = compute_metrics(clean + [far_checkout_session])
    # far_checkout is a SESSION-level anomaly (T9) -> excluded like
    # late_arrival/short_shift, same as checkin/work_duration/break_count.
    # Only the 40 clean sessions' distances count; the 12.0km far-checkout
    # value must not pull the mean up.
    assert metrics["checkout_distance_from_checkin_km"].n == 40
    assert metrics["checkout_distance_from_checkin_km"].mean == pytest.approx(1.0)
    assert metrics["checkin_time_of_day_minutes"].n == 40


def test_checkout_distance_none_contributes_nothing_and_does_not_crash():
    clean = _clean_sessions(40)  # each clean session contributes 1.0km
    open_session = _session(100, work_minutes=None, anomaly="missed_checkout")
    metrics = compute_metrics(clean + [open_session])
    # missed_checkout has no checkout coordinates at all -> None is simply
    # never appended; only the 40 clean sessions' distances count.
    assert metrics["checkout_distance_from_checkin_km"].n == 40


def test_clean_checkout_distance_included_in_self_baseline():
    sessions = [
        _session(i, checkout_distance_from_checkin_km=0.5 + i * 0.01) for i in range(40)
    ]
    metrics = compute_metrics(sessions)
    assert metrics["checkout_distance_from_checkin_km"].n == 40
    assert metrics["checkout_distance_from_checkin_km"].mean is not None


def test_peer_group_falls_back_to_company_wide_below_min_size():
    dept_id = uuid.uuid4()
    small_dept_pool = {uuid.uuid4(): _clean_sessions(40) for _ in range(3)}
    company_pool = {uuid.uuid4(): _clean_sessions(40) for _ in range(30)}
    result = build_peer_group(dept_id, small_dept_pool, company_pool, min_department_size=20)
    assert result.source == "company_wide"
    assert result.department_id is None
    assert result.pool_size == 30


def test_peer_group_uses_department_at_or_above_min_size():
    dept_id = uuid.uuid4()
    dept_pool = {uuid.uuid4(): _clean_sessions(40) for _ in range(20)}
    company_pool = {uuid.uuid4(): _clean_sessions(40) for _ in range(100)}
    result = build_peer_group(dept_id, dept_pool, company_pool, min_department_size=20)
    assert result.source == "department"
    assert result.department_id == dept_id
    assert result.pool_size == 20


def test_peer_group_department_id_none_always_falls_back():
    company_pool = {uuid.uuid4(): _clean_sessions(40) for _ in range(30)}
    result = build_peer_group(None, {}, company_pool, min_department_size=20)
    assert result.source == "company_wide"


def test_peer_group_single_employee_department_does_not_divide_by_near_zero():
    dept_id = uuid.uuid4()
    dept_pool = {uuid.uuid4(): _clean_sessions(40)}
    company_pool = {uuid.uuid4(): _clean_sessions(40) for _ in range(50)}
    result = build_peer_group(dept_id, dept_pool, company_pool, min_department_size=20)
    assert result.source == "company_wide"
    for m in METRICS:
        assert result.metrics[m].std is not None


def test_to_metric_stats_json_matches_employee_baseline_docstring_shape():
    employee_id = uuid.uuid4()
    self_baseline = build_for_employee(employee_id, _clean_sessions(40))
    dept_id = uuid.uuid4()
    dept_pool = {uuid.uuid4(): _clean_sessions(40) for _ in range(20)}
    company_pool = {uuid.uuid4(): _clean_sessions(40) for _ in range(50)}
    peer = build_peer_group(dept_id, dept_pool, company_pool, min_department_size=20)

    payload = to_metric_stats_json(self_baseline, peer)
    assert set(payload) == set(METRICS)
    for metric in METRICS:
        assert set(payload[metric]) == {"self", "peer"}
        assert set(payload[metric]["self"]) == {"mean", "std", "n"}
        assert set(payload[metric]["peer"]) == {"mean", "std", "n", "source", "department_id"}
        assert payload[metric]["peer"]["source"] == "department"
        assert payload[metric]["peer"]["department_id"] == str(dept_id)


def test_deterministic_pure_function_same_input_same_output():
    sessions = _clean_sessions(40)
    a = compute_metrics(sessions)
    b = compute_metrics(sessions)
    for m in METRICS:
        assert a[m].mean == b[m].mean
        assert a[m].std == b[m].std
        assert a[m].n == b[m].n
