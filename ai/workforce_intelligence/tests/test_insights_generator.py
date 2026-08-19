from datetime import datetime, timezone

from workforce_intelligence.insights.generator import summarize_flag

OCCURRED = datetime(2026, 8, 15, 9, 10, tzinfo=timezone.utc)


def test_summarize_flag_above_baseline_with_peer_outlier():
    text = summarize_flag(
        metric="break_duration_minutes",
        observed_value=71.0,
        self_mean=50.0,
        self_std=5.0,
        self_z=4.2,
        peer_z=3.1,
        occurred_at=OCCURRED,
    )
    assert "Break duration" in text
    assert "42% above your typical pattern" in text
    assert "1h 11m vs your usual 50m" in text
    assert "first observed 2026-08-15" in text
    assert "Also outside your department's typical range." in text


def test_summarize_flag_below_baseline_within_peer_range():
    text = summarize_flag(
        metric="work_duration_minutes",
        observed_value=300.0,
        self_mean=480.0,
        self_std=20.0,
        self_z=-9.0,
        peer_z=0.4,
        occurred_at=OCCURRED,
    )
    assert "below your typical pattern" in text
    assert "Within your department's typical range." in text


def test_summarize_flag_no_peer_data():
    text = summarize_flag(
        metric="break_count",
        observed_value=5.0,
        self_mean=1.0,
        self_std=0.5,
        self_z=8.0,
        peer_z=None,
        occurred_at=OCCURRED,
    )
    assert text.endswith("first observed 2026-08-15.")


def test_summarize_flag_degenerate_zero_variance_self_z_none():
    text = summarize_flag(
        metric="geofence_exit_count",
        observed_value=3.0,
        self_mean=0.0,
        self_std=0.0,
        self_z=None,
        peer_z=None,
        occurred_at=OCCURRED,
    )
    assert "has been exactly 0" in text
    assert "this occurrence was 3" in text
    assert "break from that fixed pattern" in text


def test_summarize_flag_checkin_time_formats_as_clock_time():
    text = summarize_flag(
        metric="checkin_time_of_day_minutes",
        observed_value=630.0,  # 10:30
        self_mean=510.0,  # 08:30
        self_std=10.0,
        self_z=12.0,
        peer_z=None,
        occurred_at=OCCURRED,
    )
    assert "10:30 vs your usual 08:30" in text


def test_summarize_flag_zero_mean_nonzero_std_falls_back_to_sigma():
    text = summarize_flag(
        metric="geofence_exit_count",
        observed_value=4.0,
        self_mean=0.0,
        self_std=1.0,
        self_z=4.0,
        peer_z=None,
        occurred_at=OCCURRED,
    )
    assert "4.0σ above your typical pattern" in text
