import uuid
from datetime import date

import pytest

from workforce_intelligence.exceptions import SyntheticConfigError
from workforce_intelligence.synthetic.generator import (
    ANOMALY_TYPES,
    BREAK_LEVEL_ANOMALIES,
    GEOFENCE_LEVEL_ANOMALIES,
    SESSION_LEVEL_ANOMALIES,
    AnomalyConfig,
    EmployeeProfile,
    generate,
)

HOME_LAT = 36.8065
HOME_LNG = 10.1815


def _profile(hire_date=date(2025, 1, 1), employee_id=None) -> EmployeeProfile:
    return EmployeeProfile(
        employee_id=employee_id or uuid.uuid4(),
        hire_date=hire_date,
        home_latitude=HOME_LAT,
        home_longitude=HOME_LNG,
    )


def test_determinism_same_seed_produces_identical_corpus():
    profile = _profile()
    config = AnomalyConfig.from_dict({"late_arrival": 0.3, "long_break": 0.2})
    result_a = generate(
        [profile], date(2025, 6, 1), date(2025, 6, 30), config, seed=42
    )
    result_b = generate(
        [profile], date(2025, 6, 1), date(2025, 6, 30), config, seed=42
    )
    assert [s.check_in_at for s in result_a.sessions] == [s.check_in_at for s in result_b.sessions]
    assert [s.synthetic_anomaly_type for s in result_a.sessions] == [
        s.synthetic_anomaly_type for s in result_b.sessions
    ]
    assert result_a.anomaly_counts == result_b.anomaly_counts


def test_different_seed_produces_different_corpus():
    profile = _profile()
    config = AnomalyConfig.from_dict({"late_arrival": 0.3})
    result_a = generate([profile], date(2025, 6, 1), date(2025, 6, 30), config, seed=1)
    result_b = generate([profile], date(2025, 6, 1), date(2025, 6, 30), config, seed=2)
    assert [s.check_in_at for s in result_a.sessions] != [s.check_in_at for s in result_b.sessions]


def test_only_work_days_generated():
    profile = _profile()
    config = AnomalyConfig.from_dict({})
    result = generate([profile], date(2025, 6, 2), date(2025, 6, 8), config, seed=7)
    # 2025-06-02 is a Monday: exactly 5 work days (Mon-Fri) in that week.
    assert len(result.sessions) == 5
    assert all(s.attendance_date.weekday() < 5 for s in result.sessions)


def test_sessions_before_hire_date_excluded():
    profile = _profile(hire_date=date(2025, 6, 5))
    config = AnomalyConfig.from_dict({})
    result = generate([profile], date(2025, 6, 1), date(2025, 6, 8), config, seed=3)
    assert all(s.attendance_date >= date(2025, 6, 5) for s in result.sessions)


def test_no_eligible_days_yields_no_sessions():
    profile = _profile(hire_date=date(2025, 7, 1))
    config = AnomalyConfig.from_dict({})
    result = generate([profile], date(2025, 6, 1), date(2025, 6, 30), config, seed=3)
    assert result.sessions == []


def test_anomaly_labels_land_on_the_right_row_level():
    profile = _profile()
    # Rates high enough that every anomaly type shows up at least once across
    # a 90-day window with a fixed seed (deterministic, not flaky).
    config = AnomalyConfig.from_dict({t: 1.0 / len(ANOMALY_TYPES) for t in ANOMALY_TYPES})
    result = generate([profile], date(2025, 1, 1), date(2025, 6, 30), config, seed=11)

    seen = set(result.anomaly_counts) & {t for t, c in result.anomaly_counts.items() if c > 0}
    assert seen, "expected at least some anomalies with these rates over 6 months"

    for session in result.sessions:
        if session.synthetic_anomaly_type is not None:
            assert session.synthetic_anomaly_type in SESSION_LEVEL_ANOMALIES
        for b in session.breaks:
            if b.synthetic_anomaly_type is not None:
                assert b.synthetic_anomaly_type in BREAK_LEVEL_ANOMALIES
                # A session can carry a break-level anomaly without itself
                # being flagged — the session-level label must stay None.
                assert session.synthetic_anomaly_type is None
        for e in session.geofence_events:
            if e.synthetic_anomaly_type is not None:
                assert e.synthetic_anomaly_type in GEOFENCE_LEVEL_ANOMALIES
                assert session.synthetic_anomaly_type is None


def test_referential_and_temporal_consistency():
    profile = _profile()
    config = AnomalyConfig.from_dict(
        {"long_break": 0.3, "excessive_geofence_exits": 0.3, "missed_checkout": 0.3}
    )
    result = generate([profile], date(2025, 1, 1), date(2025, 3, 31), config, seed=5)

    for session in result.sessions:
        if session.check_out_at is not None:
            assert session.check_in_at < session.check_out_at
        for b in session.breaks:
            assert session.check_in_at <= b.break_start_at < b.break_end_at
            if session.check_out_at is not None:
                assert b.break_end_at <= session.check_out_at
        events = session.geofence_events
        assert events[0].event_type == "enter"
        assert events[0].occurred_at == session.check_in_at
        # Every EXIT must be followed by a RETURN before the next EXIT (or
        # end of list), and both must fall strictly after check-in.
        for event in events[1:]:
            assert event.occurred_at > session.check_in_at
            if session.check_out_at is not None:
                assert event.occurred_at < session.check_out_at
        exits_and_returns = [e.event_type for e in events[1:]]
        assert len(exits_and_returns) % 2 == 0
        # Strict alternation exit, return, exit, return, ...
        for i in range(0, len(exits_and_returns) - 1, 2):
            assert exits_and_returns[i] == "exit"
            assert exits_and_returns[i + 1] == "return"


def test_missed_checkout_only_on_last_eligible_day_and_at_most_once_per_employee():
    profile = _profile()
    config = AnomalyConfig.from_dict({"missed_checkout": 0.5})
    result = generate([profile], date(2025, 1, 1), date(2025, 3, 31), config, seed=9)

    open_sessions = [s for s in result.sessions if s.check_out_at is None]
    assert len(open_sessions) <= 1
    if open_sessions:
        last_work_day = max(s.attendance_date for s in result.sessions)
        assert open_sessions[0].attendance_date == last_work_day
        assert open_sessions[0].synthetic_anomaly_type == "missed_checkout"


def test_missed_checkout_never_generated_for_employee_with_real_open_session():
    profile = _profile()
    config = AnomalyConfig.from_dict({"missed_checkout": 0.5})
    result = generate(
        [profile],
        date(2025, 1, 1),
        date(2025, 1, 31),
        config,
        seed=13,
        employees_with_open_session=frozenset({profile.employee_id}),
    )
    assert all(s.check_out_at is not None for s in result.sessions)


def test_late_arrival_sets_status_late():
    profile = _profile()
    config = AnomalyConfig.from_dict({"late_arrival": 0.5})
    result = generate([profile], date(2025, 1, 1), date(2025, 2, 28), config, seed=17)
    late_sessions = [s for s in result.sessions if s.synthetic_anomaly_type == "late_arrival"]
    assert late_sessions
    assert all(s.status == "late" for s in late_sessions)


def test_far_checkout_places_checkout_far_from_checkin():
    profile = _profile()
    config = AnomalyConfig.from_dict({"far_checkout": 0.5})
    result = generate([profile], date(2025, 1, 1), date(2025, 2, 28), config, seed=19)
    far_sessions = [s for s in result.sessions if s.synthetic_anomaly_type == "far_checkout"]
    assert far_sessions
    for s in far_sessions:
        assert abs(s.check_out_latitude - s.check_in_latitude) > 0.01 or abs(
            s.check_out_longitude - s.check_in_longitude
        ) > 0.01


def test_invalid_date_range_raises():
    profile = _profile()
    config = AnomalyConfig.from_dict({})
    with pytest.raises(SyntheticConfigError):
        generate([profile], date(2025, 6, 30), date(2025, 6, 1), config, seed=1)


def test_unknown_anomaly_type_raises():
    with pytest.raises(SyntheticConfigError):
        AnomalyConfig.from_dict({"not_a_real_anomaly": 0.1})


def test_anomaly_rate_out_of_bounds_raises():
    with pytest.raises(SyntheticConfigError):
        AnomalyConfig.from_dict({"late_arrival": 0.9})
    with pytest.raises(SyntheticConfigError):
        AnomalyConfig.from_dict({"late_arrival": -0.1})
