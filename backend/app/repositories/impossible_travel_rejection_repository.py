import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.impossible_travel_rejection import ImpossibleTravelRejection


class ImpossibleTravelRejectionRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        employee_id: uuid.UUID,
        prior_attendance_id: uuid.UUID | None,
        attempted_at: datetime,
        distance_km: float,
        elapsed_hours: float,
        implied_speed_kmh: float,
        risk_score: float,
    ) -> ImpossibleTravelRejection:
        row = ImpossibleTravelRejection(
            employee_id=employee_id,
            prior_attendance_id=prior_attendance_id,
            attempted_at=attempted_at,
            distance_km=distance_km,
            elapsed_hours=elapsed_hours,
            implied_speed_kmh=implied_speed_kmh,
            risk_score=risk_score,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_paginated(
        self,
        employee_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ImpossibleTravelRejection], int]:
        stmt = select(ImpossibleTravelRejection)
        count_stmt = select(func.count()).select_from(ImpossibleTravelRejection)
        if employee_id is not None:
            stmt = stmt.where(ImpossibleTravelRejection.employee_id == employee_id)
            count_stmt = count_stmt.where(ImpossibleTravelRejection.employee_id == employee_id)
        if date_from is not None:
            stmt = stmt.where(func.date(ImpossibleTravelRejection.attempted_at) >= date_from)
            count_stmt = count_stmt.where(
                func.date(ImpossibleTravelRejection.attempted_at) >= date_from
            )
        if date_to is not None:
            stmt = stmt.where(func.date(ImpossibleTravelRejection.attempted_at) <= date_to)
            count_stmt = count_stmt.where(
                func.date(ImpossibleTravelRejection.attempted_at) <= date_to
            )
        total = (await self._session.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(ImpossibleTravelRejection.attempted_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total
