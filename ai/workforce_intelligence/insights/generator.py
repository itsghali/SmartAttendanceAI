"""Insight generation (Module 4).

Pure, DB-agnostic (mirrors ai/workforce_intelligence/baseline/builder.py and
detection/detector.py's style) — the caller
(backend/app/services/workforce_intelligence_service.py) supplies plain
values pulled off an already-persisted EmployeeDeviationFlag row; this
module only formats.

Approach A (PLAN.md's Module 4 CEO-phase review, Step 0C-bis): rule-based
template prose off the flag's own fields, no SHAP, no LLM. Module 3 scores a
single metric's z-score against the employee's own baseline — the metric
name IS the reason a flag exists, so there is no multi-feature model for
SHAP to explain. The Section 2 CEO-review "SHAP degenerate-variance GAP" is
therefore moot under this approach, not worked around — self_z=None (a
zero-variance baseline, see detection/detector.py) gets its own template
branch below rather than a SHAP fallback.
"""

from __future__ import annotations

from datetime import datetime

# Human label + unit formatter per Module 3 metric name. Keys must match
# ai/workforce_intelligence/baseline/builder.py's METRICS exactly.
_METRIC_LABELS: dict[str, str] = {
    "checkin_time_of_day_minutes": "Check-in time",
    "work_duration_minutes": "Work duration",
    "break_duration_minutes": "Break duration",
    "break_count": "Number of breaks",
    "geofence_exit_count": "Number of site exits",
}

# z >= 2.5 mirrors detection/detector.py's own Z_SCORE_THRESHOLD — reused
# here as the bar for whether the peer clause is worth stating at all,
# not a second independently-tuned threshold.
_PEER_NOTE_Z_THRESHOLD = 2.5


def _format_minutes_of_day(value: float) -> str:
    minutes = int(round(value)) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _format_value(metric: str, value: float) -> str:
    if metric == "checkin_time_of_day_minutes":
        return _format_minutes_of_day(value)
    if metric in ("work_duration_minutes", "break_duration_minutes"):
        hours, minutes = divmod(int(round(value)), 60)
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"
    if metric in ("break_count", "geofence_exit_count"):
        return str(int(round(value)))
    return f"{value:.1f}"


def _peer_clause(peer_z: float | None) -> str:
    if peer_z is None:
        return ""
    if abs(peer_z) >= _PEER_NOTE_Z_THRESHOLD:
        return " Also outside your department's typical range."
    return " Within your department's typical range."


def summarize_flag(
    *,
    metric: str,
    observed_value: float,
    self_mean: float,
    self_std: float,
    self_z: float | None,
    peer_z: float | None,
    occurred_at: datetime,
) -> str:
    """Turns one EmployeeDeviationFlag's fields into a plain-English
    sentence. Every number in the output is traceable back to the exact
    stored field it came from — no inference, no model output."""
    label = _METRIC_LABELS.get(metric, metric.replace("_", " ").capitalize())
    observed_fmt = _format_value(metric, observed_value)
    mean_fmt = _format_value(metric, self_mean)
    when = occurred_at.date().isoformat()

    if self_z is None:
        # Degenerate zero-variance baseline (self_std == 0.0) — detector.py
        # only emits a flag here when the value differs from that fixed
        # mean at all, so "percent above/below" is undefined; describe the
        # break from a constant instead.
        return (
            f"Your {label.lower()} has been exactly {mean_fmt} until now; this "
            f"occurrence was {observed_fmt}, a break from that fixed pattern."
            f"{_peer_clause(peer_z)}"
        )

    direction = "above" if observed_value >= self_mean else "below"
    if self_mean != 0:
        pct = abs((observed_value - self_mean) / self_mean) * 100
        magnitude = f"{pct:.0f}%"
    else:
        # mean of exactly 0 with nonzero std (e.g. geofence_exit_count
        # baseline centered at 0 but with some spread) — percent-of-zero is
        # undefined; fall back to the z-score itself as the magnitude.
        magnitude = f"{abs(self_z):.1f}σ"

    return (
        f"{label} was {magnitude} {direction} your typical pattern "
        f"({observed_fmt} vs your usual {mean_fmt}), first observed {when}."
        f"{_peer_clause(peer_z)}"
    )
