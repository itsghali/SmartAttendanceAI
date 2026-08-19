import uuid
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_deviation_flag import (
    DeviationSeverity,
    EmployeeDeviationFlag,
    ReviewStatus,
)


class EmployeeDeviationFlagRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def delete_for_employee_window(
        self, employee_id: uuid.UUID, window_start: date, window_end: date
    ) -> None:
        """A detection re-run for the same (employee, window) replaces its
        prior flags rather than accumulating duplicates — same "rebuild"
        semantics as EmployeeBaseline's upsert, just at row-per-occurrence
        granularity instead of one row per employee."""
        stmt = delete(EmployeeDeviationFlag).where(
            EmployeeDeviationFlag.employee_id == employee_id,
            EmployeeDeviationFlag.window_start == window_start,
            EmployeeDeviationFlag.window_end == window_end,
        )
        await self._session.execute(stmt)

    async def bulk_create(self, rows: list[dict]) -> list[EmployeeDeviationFlag]:
        records = [EmployeeDeviationFlag(**row) for row in rows]
        self._session.add_all(records)
        await self._session.flush()
        return records

    async def list_paginated(
        self,
        employee_id: uuid.UUID | None,
        window_start: date | None,
        window_end: date | None,
        limit: int,
        offset: int,
        *,
        severity: DeviationSeverity | None = None,
        review_status: ReviewStatus | None = None,
    ) -> tuple[list[EmployeeDeviationFlag], int]:
        stmt = select(EmployeeDeviationFlag)
        count_stmt = select(func.count()).select_from(EmployeeDeviationFlag)
        if employee_id is not None:
            stmt = stmt.where(EmployeeDeviationFlag.employee_id == employee_id)
            count_stmt = count_stmt.where(EmployeeDeviationFlag.employee_id == employee_id)
        if window_start is not None:
            stmt = stmt.where(EmployeeDeviationFlag.window_start >= window_start)
            count_stmt = count_stmt.where(EmployeeDeviationFlag.window_start >= window_start)
        if window_end is not None:
            stmt = stmt.where(EmployeeDeviationFlag.window_end <= window_end)
            count_stmt = count_stmt.where(EmployeeDeviationFlag.window_end <= window_end)
        if severity is not None:
            stmt = stmt.where(EmployeeDeviationFlag.severity == severity)
            count_stmt = count_stmt.where(EmployeeDeviationFlag.severity == severity)
        if review_status is not None:
            stmt = stmt.where(EmployeeDeviationFlag.review_status == review_status)
            count_stmt = count_stmt.where(EmployeeDeviationFlag.review_status == review_status)
        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(EmployeeDeviationFlag.occurred_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_by_id(self, flag_id: uuid.UUID) -> EmployeeDeviationFlag | None:
        return await self._session.get(EmployeeDeviationFlag, flag_id)

    async def set_review_status(
        self,
        flag: EmployeeDeviationFlag,
        status: ReviewStatus,
        reviewer_id: uuid.UUID | None,
        reviewed_at: datetime,
    ) -> EmployeeDeviationFlag:
        flag.review_status = status
        flag.reviewed_by = reviewer_id
        flag.reviewed_at = reviewed_at
        await self._session.flush()
        return flag
