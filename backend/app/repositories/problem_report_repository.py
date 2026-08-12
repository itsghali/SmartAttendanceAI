import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.mixins import utcnow
from app.models.problem_report import ProblemReport, ProblemReportStatus

_EAGER = (selectinload(ProblemReport.employee).selectinload(Employee.user),)


class ProblemReportRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self, employee_id: uuid.UUID, attendance_id: uuid.UUID | None, message: str
    ) -> ProblemReport:
        report = ProblemReport(employee_id=employee_id, attendance_id=attendance_id, message=message)
        self._session.add(report)
        await self._session.flush()
        # Re-fetch through get() rather than eager-loading a freshly-added
        # row in place — `report.employee` isn't populated yet after flush,
        # and the route always renders employee_full_name/employee_code.
        return await self.get(report.id)  # type: ignore[return-value]

    async def get(self, report_id: uuid.UUID) -> ProblemReport | None:
        stmt = select(ProblemReport).options(*_EAGER).where(ProblemReport.id == report_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_paginated(
        self, status: ProblemReportStatus | None, limit: int, offset: int
    ) -> tuple[list[ProblemReport], int]:
        stmt = select(ProblemReport).options(*_EAGER)
        count_stmt = select(func.count()).select_from(ProblemReport)
        if status is not None:
            stmt = stmt.where(ProblemReport.status == status)
            count_stmt = count_stmt.where(ProblemReport.status == status)

        total = (await self._session.execute(count_stmt)).scalar_one()
        # Open-first isn't right here — newest-first within whatever the
        # caller filtered to is what an HR triage queue actually wants.
        stmt = stmt.order_by(ProblemReport.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def resolve(self, report: ProblemReport, resolved_by_id: uuid.UUID) -> None:
        report.status = ProblemReportStatus.RESOLVED
        report.resolved_at = utcnow()
        report.resolved_by_id = resolved_by_id
        await self._session.flush()
