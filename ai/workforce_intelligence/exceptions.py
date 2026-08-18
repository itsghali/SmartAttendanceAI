"""Framework-agnostic errors for the workforce_intelligence package — this
package knows nothing about FastAPI or the backend's DomainError hierarchy
(same convention as ai/face_recognition/exceptions.py). The backend's
workforce_intelligence_service.py catches these and reacts (e.g. marks a
SyntheticDataRun FAILED) rather than letting a bare Exception propagate."""


class WorkforceIntelligenceError(Exception):
    pass


class SyntheticConfigError(WorkforceIntelligenceError):
    """Request itself is invalid (bad anomaly_config, empty scope, inverted
    date range, unknown employee) — raised BEFORE a SyntheticDataRun row is
    created, so a rejected request never leaves a wasted FAILED run behind."""


class BaselineConfigError(WorkforceIntelligenceError):
    """Baseline-rebuild request itself is invalid (empty scope, inverted
    window) — raised before any EmployeeBaseline row is touched."""


class InsufficientHistoryError(WorkforceIntelligenceError):
    """Employee has fewer clean (non-anomalous) workdays than the minimum
    history window — build_for_employee refuses rather than writing a
    baseline computed from noise. Not fatal to a rebuild run: the caller
    catches this per-employee and skips, it does not abort the whole batch."""


class DetectionConfigError(WorkforceIntelligenceError):
    """Detection-run request itself is invalid (empty scope, inverted
    window) — raised before any EmployeeDeviationFlag row is touched."""
