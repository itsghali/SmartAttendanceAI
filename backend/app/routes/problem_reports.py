import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.core.exceptions import ProblemReportAlreadyResolvedError, ProblemReportNotFoundError
from app.core.rate_limit import RateLimiter, get_redis_client
from app.models.problem_report import ProblemReport, ProblemReportStatus
from app.models.user import User
from app.schemas.problem_report import ProblemReportCreate, ProblemReportListOut, ProblemReportOut
from app.services.employee_service import EmployeeService
from app.services.problem_report_service import ProblemReportService

router = APIRouter(prefix="/problem-reports", tags=["problem-reports"])


def _report_out(report: ProblemReport) -> ProblemReportOut:
    return ProblemReportOut(
        id=report.id,
        employee_id=report.employee_id,
        employee_full_name=report.employee.user.full_name,
        employee_code=report.employee.employee_code,
        attendance_id=report.attendance_id,
        message=report.message,
        status=report.status,
        created_at=report.created_at,
        resolved_at=report.resolved_at,
        resolved_by_id=report.resolved_by_id,
    )


async def _create_rate_limit(
    user: User = Depends(get_current_user), redis: Redis = Depends(get_redis_client)
) -> None:
    settings = get_settings()
    limiter = RateLimiter(
        redis,
        "problem-report",
        settings.problem_report_rate_limit_per_window,
        settings.problem_report_rate_limit_window_seconds,
    )
    await limiter.check(str(user.id))


@router.post(
    "",
    response_model=ProblemReportOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_create_rate_limit)],
)
async def create_problem_report(
    body: ProblemReportCreate,
    user: User = Depends(require_permission("problem_reports:create:own")),
    session: AsyncSession = Depends(get_db),
) -> ProblemReportOut:
    employee = await EmployeeService(session).get_or_create_own_profile(user)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no employee profile for this account"
        )
    report = await ProblemReportService(session).create(employee.id, body.attendance_id, body.message)
    return _report_out(report)


@router.get(
    "",
    response_model=ProblemReportListOut,
    dependencies=[Depends(require_permission("problem_reports:read:all"))],
)
async def list_problem_reports(
    status_filter: ProblemReportStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> ProblemReportListOut:
    reports, total = await ProblemReportService(session).list_paginated(status_filter, limit, offset)
    return ProblemReportListOut(
        items=[_report_out(r) for r in reports], total=total, limit=limit, offset=offset
    )


@router.patch(
    "/{report_id}/resolve",
    response_model=ProblemReportOut,
)
async def resolve_problem_report(
    report_id: uuid.UUID,
    user: User = Depends(require_permission("problem_reports:resolve")),
    session: AsyncSession = Depends(get_db),
) -> ProblemReportOut:
    try:
        report = await ProblemReportService(session).resolve(report_id, user.id)
    except ProblemReportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProblemReportAlreadyResolvedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _report_out(report)
