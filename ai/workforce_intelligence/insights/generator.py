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
    "checkout_distance_from_checkin_km": "Checkout distance from check-in",
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
    if metric == "checkout_distance_from_checkin_km":
        return f"{value:.1f} km"
    return f"{value:.1f}"


def _peer_clause(peer_z: float | None) -> str:
    if peer_z is None:
        return ""
    if abs(peer_z) >= _PEER_NOTE_Z_THRESHOLD:
        return " Also outside your department's typical range."
    return " Within your department's typical range."


# Per-metric presentation copy (Requirement 2's deterministic-template
# design — no LLM, no free-text generation). Keys must match
# ai/workforce_intelligence/baseline/builder.py's METRICS exactly, same
# constraint _METRIC_LABELS above already follows.
#
# "early_departure"/"late_arrival" framing from the spec only applies where
# an existing metric actually measures that: checkin_time_of_day_minutes IS
# arrival time, so late/early language is honest there. work_duration_minutes
# is session LENGTH, not a checkout timestamp — a short session could be a
# late arrival, an early departure, or both, and the metric alone can't say
# which. Titling it "Unusual Work Duration" (not "Early Departure") avoids
# asserting a specific cause the data doesn't support — see module docstring
# on inventing evidence.
_METRIC_TITLES: dict[str, str] = {
    "checkin_time_of_day_minutes": "Unusual Check-in Time",
    "work_duration_minutes": "Unusual Work Duration",
    "break_duration_minutes": "Unusual Break Duration",
    "break_count": "Unusual Number of Breaks",
    "geofence_exit_count": "Unusual Number of Site Exits",
    "checkout_distance_from_checkin_km": "Unusual Checkout Location",
}

_DETECTION_TYPE_LABELS: dict[str, str] = {
    "checkin_time_of_day_minutes": "Check-in time deviation",
    "work_duration_minutes": "Work duration deviation",
    "break_duration_minutes": "Break duration deviation",
    "break_count": "Break frequency deviation",
    "geofence_exit_count": "Site exit frequency deviation",
    "checkout_distance_from_checkin_km": "Checkout location deviation",
}

# Fixed action set every insight offers — Module 4's own review-status
# vocabulary (see EmployeeDeviationFlag.ReviewStatus), not a new one.
_RECOMMENDED_ACTIONS = [
    {"label": "View Employee", "action": "view_employee"},
    {"label": "View Evidence", "action": "view_evidence"},
    {"label": "Mark as Reviewed", "action": "mark_reviewed"},
]


def _explanation(metric: str, self_z: float | None) -> str:
    if self_z is None:
        return (
            "This pattern has been flagged because it breaks a value that has "
            "never varied for this employee before."
        )
    return (
        "This pattern has been flagged because it differs significantly from "
        "the employee's recent baseline."
    )


def build_presentation(
    *,
    metric: str,
    observed_value: float,
    self_mean: float,
    self_std: float,
    self_z: float | None,
    self_n: int | None,
    peer_mean: float,
    peer_std: float,
    peer_z: float | None,
    peer_n: int | None,
    severity: str,
    occurred_at: datetime,
    detected_at: datetime,
) -> dict:
    """Turns one flag's fields into the structured, human-readable shape
    Requirement 2 asks for: title/summary/explanation/evidence/severity/
    detected_at/recommended_action. Deterministic templates only, same
    "every number traceable to a stored field" guarantee as summarize_flag
    above — this function IS that guarantee, formalized into named fields
    instead of one prose sentence. z-scores and other internal statistics
    are deliberately kept OUT of evidence (human units only, per spec) and
    surfaced separately via the `technical` key for a "Technical Details"
    disclosure — the underlying evidence stays available, just not in the
    primary view.

    Caller-supplied (not looked up here, this module stays DB-agnostic):
    employee identity, and which of self_n/peer_n a given caller has
    available (both may be None for flag rows written before that column
    existed — see EmployeeDeviationFlag.self_n's docstring).
    """
    title = _METRIC_TITLES.get(metric, metric.replace("_", " ").capitalize())
    summary = summarize_flag(
        metric=metric,
        observed_value=observed_value,
        self_mean=self_mean,
        self_std=self_std,
        self_z=self_z,
        peer_z=peer_z,
        occurred_at=occurred_at,
    )
    observed_fmt = _format_value(metric, observed_value)
    mean_fmt = _format_value(metric, self_mean)
    if self_z is None:
        difference_fmt = "differs from a previously fixed value"
    else:
        diff = observed_value - self_mean
        sign = "+" if diff >= 0 else "-"
        difference_fmt = f"{sign}{_format_value(metric, abs(diff))}"

    evidence = {
        "current": observed_fmt,
        "baseline": mean_fmt,
        "difference": difference_fmt,
        "historical_observations": self_n,
        "severity": severity,
        "detection_type": _DETECTION_TYPE_LABELS.get(metric, metric.replace("_", " ")),
    }

    return {
        "title": title,
        "summary": summary,
        "explanation": _explanation(metric, self_z),
        "evidence": evidence,
        "technical": {
            "metric": metric,
            "self_mean": self_mean,
            "self_std": self_std,
            "self_z": self_z,
            "self_n": self_n,
            "peer_mean": peer_mean,
            "peer_std": peer_std,
            "peer_z": peer_z,
            "peer_n": peer_n,
        },
        "severity": severity,
        "detected_at": detected_at,
        "recommended_action": list(_RECOMMENDED_ACTIONS),
    }


_DISCLAIMER = (
    "This is an anomaly indicator for review, not a conclusion about "
    "employee intent or behavior."
)


def render_email(presentation: dict, *, employee_name: str, deep_link: str) -> tuple[str, str]:
    """Deterministic subject/body for the email channel — same presentation
    dict the dashboard renders from, no separate copy to keep in sync. No
    z-scores, metric identifiers, or other internal fields (Requirement 1's
    "must NOT expose unnecessary technical information")."""
    subject = f"Workforce Intelligence Alert — {presentation['title']}"
    ev = presentation["evidence"]
    lines = [
        f"An unusual attendance pattern was detected for {employee_name}.",
        "",
        presentation["summary"],
        "",
        f"Current: {ev['current']}",
        f"Usual average: {ev['baseline']}",
        f"Difference: {ev['difference']}",
        "",
        presentation["explanation"],
        "",
        f"View details: {deep_link}",
        "",
        _DISCLAIMER,
    ]
    return subject, "\n".join(lines)


def render_digest_email(presentations: list[dict], *, deep_link: str) -> tuple[str, str]:
    """One email bundling several lower-severity insights (Requirement 1's
    aggregation rule) instead of one email per anomaly."""
    subject = f"Workforce Intelligence — {len(presentations)} attendance pattern(s) to review"
    lines = [
        f"{len(presentations)} attendance pattern(s) were flagged for review "
        "since the last summary:",
        "",
    ]
    for p in presentations:
        lines.append(f"- {p['title']}: {p['summary']}")
    lines += ["", f"View details: {deep_link}", "", _DISCLAIMER]
    return subject, "\n".join(lines)


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
