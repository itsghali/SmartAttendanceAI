import uuid
from datetime import datetime, timedelta, timezone

from app.models.geofence_event import GeofenceEvent, GeofenceEventType
from app.routes.attendance import _pair_exit_durations


def _event(attendance_id, event_type, created_at):
    return GeofenceEvent(
        id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        attendance_id=attendance_id,
        geofence_id=None,
        event_type=event_type,
        latitude=0.0,
        longitude=0.0,
        created_at=created_at,
    )


def test_closed_pair_computes_duration_minutes():
    attendance_id = uuid.uuid4()
    t0 = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)
    exit_event = _event(attendance_id, GeofenceEventType.EXIT, t0)
    return_event = _event(attendance_id, GeofenceEventType.RETURN, t0 + timedelta(minutes=12))

    durations = _pair_exit_durations([exit_event, return_event], {})

    assert durations[exit_event.id] == (12, False)
    assert return_event.id not in durations


def test_open_exit_has_no_duration_and_still_open_true():
    attendance_id = uuid.uuid4()
    t0 = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)
    exit_event = _event(attendance_id, GeofenceEventType.EXIT, t0)

    durations = _pair_exit_durations([exit_event], {attendance_id: None})

    assert durations[exit_event.id] == (None, True)


def test_multiple_exit_return_cycles_pair_independently():
    attendance_id = uuid.uuid4()
    t0 = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)
    exit1 = _event(attendance_id, GeofenceEventType.EXIT, t0)
    return1 = _event(attendance_id, GeofenceEventType.RETURN, t0 + timedelta(minutes=5))
    exit2 = _event(attendance_id, GeofenceEventType.EXIT, t0 + timedelta(minutes=30))
    return2 = _event(attendance_id, GeofenceEventType.RETURN, t0 + timedelta(minutes=45))

    # Shuffled order on purpose — list_all_for_employee returns created_at
    # desc, callers must not depend on input order.
    durations = _pair_exit_durations([return2, exit1, return1, exit2], {})

    assert durations[exit1.id] == (5, False)
    assert durations[exit2.id] == (15, False)


def test_pairing_never_crosses_attendance_sessions():
    session_a = uuid.uuid4()
    session_b = uuid.uuid4()
    t0 = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)
    exit_a = _event(session_a, GeofenceEventType.EXIT, t0)
    return_b = _event(session_b, GeofenceEventType.RETURN, t0 + timedelta(minutes=10))

    durations = _pair_exit_durations([exit_a, return_b], {session_a: None})

    # exit_a has no RETURN in its own session — still open, must not pair
    # with session_b's unrelated RETURN even though it's chronologically after.
    assert durations[exit_a.id] == (None, True)


def test_empty_and_return_only_groups_produce_no_entries():
    assert _pair_exit_durations([], {}) == {}

    attendance_id = uuid.uuid4()
    t0 = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)
    return_only = _event(attendance_id, GeofenceEventType.RETURN, t0)
    durations = _pair_exit_durations([return_only], {attendance_id: None})
    assert durations == {}


def test_exit_with_no_return_but_session_checked_out_is_closed_not_still_open():
    # The real bug this test guards: an employee exits, never returns, and
    # checks out anyway (from outside the zone, or a supervisor correction).
    # Session is CLOSED — must not read as "still outside" forever after.
    attendance_id = uuid.uuid4()
    t0 = datetime(2026, 8, 11, 12, 49, 25, tzinfo=timezone.utc)
    exit_event = _event(attendance_id, GeofenceEventType.EXIT, t0)
    checkout_at = t0 + timedelta(minutes=3)

    durations = _pair_exit_durations([exit_event], {attendance_id: checkout_at})

    assert durations[exit_event.id] == (3, False)


def test_return_present_takes_priority_over_checkout_boundary():
    attendance_id = uuid.uuid4()
    t0 = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)
    exit_event = _event(attendance_id, GeofenceEventType.EXIT, t0)
    return_event = _event(attendance_id, GeofenceEventType.RETURN, t0 + timedelta(minutes=8))
    checkout_at = t0 + timedelta(minutes=40)

    durations = _pair_exit_durations([exit_event, return_event], {attendance_id: checkout_at})

    # RETURN happened well before checkout — duration is EXIT->RETURN (8),
    # not EXIT->checkout (40).
    assert durations[exit_event.id] == (8, False)


def test_checkout_before_exit_is_ignored_still_reads_as_still_open():
    # Defensive: a checkout timestamp that predates this EXIT can't be its
    # closing boundary (shouldn't happen in practice — checkout implies the
    # session is over — but must not produce a negative/nonsense duration).
    attendance_id = uuid.uuid4()
    t0 = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)
    checkout_at = t0 - timedelta(minutes=5)
    exit_event = _event(attendance_id, GeofenceEventType.EXIT, t0)

    durations = _pair_exit_durations([exit_event], {attendance_id: checkout_at})

    assert durations[exit_event.id] == (None, True)


def test_missing_attendance_id_in_checkout_map_defaults_to_still_open():
    # checkout_at_by_attendance is keyed off ALL of the employee's sessions
    # in range — an attendance_id genuinely absent from it (shouldn't happen
    # given how the route builds it, but the function must not KeyError).
    attendance_id = uuid.uuid4()
    t0 = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)
    exit_event = _event(attendance_id, GeofenceEventType.EXIT, t0)

    durations = _pair_exit_durations([exit_event], {})

    assert durations[exit_event.id] == (None, True)
