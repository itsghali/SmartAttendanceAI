import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.employee_deviation_flag import DeviationSeverity


class NotificationOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    deviation_flag_id: uuid.UUID | None
    metric: str
    severity: DeviationSeverity
    title: str
    summary: str
    evidence: dict
    recommended_action: list[dict]
    occurred_at: datetime
    detected_at: datetime
    is_read: bool
    read_at: datetime | None
    email_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    limit: int
    offset: int


class UnreadCountOut(BaseModel):
    unread_count: int
