import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.models.employee_deviation_flag import DeviationSeverity, ReviewStatus
from app.models.synthetic_data_run import SyntheticDataRunStatus

# T5: sane upper bounds on BOTH generate's and rebuild's request scope
# (Claude subagent finding — the original plan draft only bounded generate,
# leaving rebuild unbounded). Enforced here at the schema layer so an
# oversized request 422s before the route/service ever sees it, not just
# documented as a should-do.
MAX_EMPLOYEES_PER_REQUEST = 200
MAX_DATE_RANGE_DAYS = 400


class _DateRangeMixin(BaseModel):
    @model_validator(mode="after")
    def _check_date_range(self) -> "_DateRangeMixin":
        start, end = self._date_range()
        if end < start:
            raise ValueError("range end must not precede range start")
        if (end - start).days > MAX_DATE_RANGE_DAYS:
            raise ValueError(f"range must not exceed {MAX_DATE_RANGE_DAYS} days")
        return self

    def _date_range(self) -> tuple[date, date]:
        raise NotImplementedError


class SyntheticDataGenerateRequest(_DateRangeMixin):
    employee_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_EMPLOYEES_PER_REQUEST)
    date_range_start: date
    date_range_end: date
    anomaly_config: dict = Field(default_factory=dict)
    seed: int
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)

    def _date_range(self) -> tuple[date, date]:
        return self.date_range_start, self.date_range_end


class SyntheticDataRunOut(BaseModel):
    id: uuid.UUID
    status: SyntheticDataRunStatus
    employee_scope: list[str]
    date_range_start: date
    date_range_end: date
    anomaly_config: dict
    error_message: str | None
    row_counts: dict | None
    idempotency_key: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BaselineRebuildRequest(_DateRangeMixin):
    employee_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_EMPLOYEES_PER_REQUEST)
    window_start: date
    window_end: date

    def _date_range(self) -> tuple[date, date]:
        return self.window_start, self.window_end


class BaselineRebuildResultOut(BaseModel):
    built: list[uuid.UUID]
    skipped_insufficient_history: list[uuid.UUID]
    skipped_terminated: list[uuid.UUID]


class EmployeeBaselineOut(BaseModel):
    employee_id: uuid.UUID
    window_start: date
    window_end: date
    metric_stats: dict
    computed_at: datetime

    model_config = {"from_attributes": True}


class DetectionRunRequest(_DateRangeMixin):
    employee_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_EMPLOYEES_PER_REQUEST)
    window_start: date
    window_end: date

    def _date_range(self) -> tuple[date, date]:
        return self.window_start, self.window_end


class DetectionRunResultOut(BaseModel):
    scored: list[uuid.UUID]
    skipped_no_baseline: list[uuid.UUID]
    flag_counts: dict[str, int]


class EmployeeDeviationFlagOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    attendance_id: uuid.UUID
    metric: str
    occurred_at: datetime
    observed_value: float
    self_mean: float
    self_std: float
    self_z: float | None
    self_n: int | None
    peer_mean: float
    peer_std: float
    peer_z: float | None
    peer_n: int | None
    severity: DeviationSeverity
    window_start: date
    window_end: date
    detected_at: datetime
    is_synthetic: bool
    synthetic_anomaly_type: str | None
    review_status: ReviewStatus
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None

    model_config = {"from_attributes": True}


class EmployeeDeviationFlagListOut(BaseModel):
    items: list[EmployeeDeviationFlagOut]
    total: int
    limit: int
    offset: int


class WorkforceInsightOut(EmployeeDeviationFlagOut):
    """Module 4 — same fields as a raw EmployeeDeviationFlagOut (evidence
    view, HR/Admin can drill down to the exact numbers) plus the
    Requirement-2 human-readable presentation. Always HIGH severity — see
    WorkforceIntelligenceService.list_insights's evidence-threshold note.

    `summary`/`explanation`/`evidence`/`recommended_action` are the primary,
    human-facing fields (no metric identifiers or z-scores); `technical`
    carries the same underlying statistics the raw EmployeeDeviationFlagOut
    fields above already expose, kept here too so a client can render the
    "Technical Details" disclosure straight off one object.
    """

    title: str
    summary: str
    explanation: str
    evidence: dict
    technical: dict
    recommended_action: list[dict]


class WorkforceInsightListOut(BaseModel):
    items: list[WorkforceInsightOut]
    total: int
    limit: int
    offset: int


class ReviewFlagRequest(BaseModel):
    status: ReviewStatus


class ImpossibleTravelRejectionOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    prior_attendance_id: uuid.UUID | None
    attempted_at: datetime
    distance_km: float
    elapsed_hours: float
    implied_speed_kmh: float
    risk_score: float
    created_at: datetime

    model_config = {"from_attributes": True}


class ImpossibleTravelRejectionListOut(BaseModel):
    items: list[ImpossibleTravelRejectionOut]
    total: int
    limit: int
    offset: int
