import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.problem_report import ProblemReportStatus


class ProblemReportCreate(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # The open attendance session at the moment of reporting, if any — lets
    # HR jump straight to the relevant check-in/out without the employee
    # having to describe which one. Optional: a report isn't always tied to
    # a specific action.
    attendance_id: uuid.UUID | None = None


class ProblemReportOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_full_name: str
    employee_code: str
    attendance_id: uuid.UUID | None
    message: str
    status: ProblemReportStatus
    created_at: datetime
    resolved_at: datetime | None
    resolved_by_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class ProblemReportListOut(BaseModel):
    items: list[ProblemReportOut]
    total: int
    limit: int
    offset: int
