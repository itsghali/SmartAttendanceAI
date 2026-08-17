import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.synthetic_data_run import SyntheticDataRun, SyntheticDataRunStatus


class SyntheticDataRunRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        requested_by: uuid.UUID | None,
        employee_scope: list[str],
        date_range_start: date,
        date_range_end: date,
        anomaly_config: dict,
    ) -> SyntheticDataRun:
        run = SyntheticDataRun(
            requested_by=requested_by,
            employee_scope=employee_scope,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            anomaly_config=anomaly_config,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> SyntheticDataRun | None:
        stmt = select(SyntheticDataRun).where(SyntheticDataRun.id == run_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def set_status(
        self,
        run: SyntheticDataRun,
        status: SyntheticDataRunStatus,
        error_message: str | None = None,
        row_counts: dict | None = None,
    ) -> None:
        run.status = status
        if error_message is not None:
            run.error_message = error_message
        if row_counts is not None:
            run.row_counts = row_counts
        await self._session.flush()
