import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProblemReportAlreadyResolvedError, ProblemReportNotFoundError
from app.models.problem_report import ProblemReport, ProblemReportStatus
from app.repositories.problem_report_repository import ProblemReportRepository


class ProblemReportService:
    def __init__(self, session: AsyncSession):
        self._reports = ProblemReportRepository(session)

    async def create(
        self, employee_id: uuid.UUID, attendance_id: uuid.UUID | None, message: str
    ) -> ProblemReport:
        return await self._reports.create(employee_id, attendance_id, message)

    async def get(self, report_id: uuid.UUID) -> ProblemReport | None:
        return await self._reports.get(report_id)

    async def list_paginated(
        self, status: ProblemReportStatus | None, limit: int, offset: int
    ) -> tuple[list[ProblemReport], int]:
        return await self._reports.list_paginated(status, limit, offset)

    async def resolve(self, report_id: uuid.UUID, resolved_by_id: uuid.UUID) -> ProblemReport:
        report = await self._reports.get(report_id)
        if report is None:
            raise ProblemReportNotFoundError(f"problem report {report_id} not found")
        if report.status == ProblemReportStatus.RESOLVED:
            raise ProblemReportAlreadyResolvedError(
                f"problem report {report_id} is already resolved"
            )
        await self._reports.resolve(report, resolved_by_id)
        return report
