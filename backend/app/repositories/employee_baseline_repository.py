import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_baseline import EmployeeBaseline


class EmployeeBaselineRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_employee_id(self, employee_id: uuid.UUID) -> EmployeeBaseline | None:
        stmt = select(EmployeeBaseline).where(EmployeeBaseline.employee_id == employee_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def upsert(
        self,
        employee_id: uuid.UUID,
        window_start: date,
        window_end: date,
        metric_stats: dict,
        computed_at: datetime,
    ) -> EmployeeBaseline:
        """One row per employee (unique employee_id, per the model's own
        docstring) — a rebuild replaces the previous baseline in place
        rather than accumulating history-of-baselines rows."""
        existing = await self.get_by_employee_id(employee_id)
        if existing is not None:
            existing.window_start = window_start
            existing.window_end = window_end
            existing.metric_stats = metric_stats
            existing.computed_at = computed_at
            await self._session.flush()
            return existing

        baseline = EmployeeBaseline(
            employee_id=employee_id,
            window_start=window_start,
            window_end=window_end,
            metric_stats=metric_stats,
            computed_at=computed_at,
        )
        self._session.add(baseline)
        await self._session.flush()
        return baseline
