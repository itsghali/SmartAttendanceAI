"""Orchestrates Module 1 (synthetic data generation) and Module 2
(per-employee/peer-group baselines).

Module 1: validates the request, runs the pure ai/workforce_intelligence
generator, and persists the result as one all-or-nothing transaction tagged
to a SyntheticDataRun (PLAN.md T2).

Module 2: batch-loads Attendance history for the requested employees (ONE
query, including synthetic rows — see AttendanceRepository
.list_for_baseline_including_synthetic's docstring for why this is the one
deliberate exception to T0/T1), converts it into the pure builder's input
shape, and upserts one EmployeeBaseline row per employee that clears the
minimum-history threshold.

Imports ai/workforce_intelligence in-process via the same sys.path-injection
technique face_service.py already uses for ai/face_recognition — no new
deployment topology.

Scope note: detection/insight orchestration (Modules 3-4) are separate,
not-yet-built sprints — see PLAN.md.
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import Attendance, AttendanceStatus
from app.models.break_period import BreakSource
from app.models.employee import EmployeeStatus
from app.models.geofence_event import GeofenceEventType
from app.models.mixins import utcnow
from app.models.synthetic_data_run import SyntheticDataRun, SyntheticDataRunStatus
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.break_period_repository import BreakPeriodRepository
from app.repositories.employee_baseline_repository import EmployeeBaselineRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.geofence_event_repository import GeofenceEventRepository
from app.repositories.geofence_repository import GeofenceRepository
from app.repositories.synthetic_data_run_repository import SyntheticDataRunRepository

_AI_DIR = Path(__file__).resolve().parents[3] / "ai"
if str(_AI_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_DIR))

from workforce_intelligence.baseline import builder as baseline_builder  # noqa: E402
from workforce_intelligence.exceptions import (  # noqa: E402
    BaselineConfigError,
    InsufficientHistoryError,
    SyntheticConfigError,
)
from workforce_intelligence.synthetic import generator as synthetic_generator  # noqa: E402

logger = logging.getLogger("app.workforce_intelligence")


class SyntheticGenerationError(Exception):
    """Raised after a SyntheticDataRun has already been recorded FAILED
    (PLAN.md T2) — the run row's error_message carries the real detail; this
    is just the signal to the caller that the request did not complete."""


def _to_attendance_record(a: Attendance) -> baseline_builder.AttendanceRecord:
    # Open breaks (break_end_at is None) contribute no duration data point
    # and are excluded outright, from both break_count and break_duration —
    # an in-progress break isn't a completed observation yet.
    breaks = [
        baseline_builder.BreakRecord(
            duration_minutes=(b.break_end_at - b.break_start_at).total_seconds() / 60,
            synthetic_anomaly_type=b.synthetic_anomaly_type,
        )
        for b in a.breaks
        if b.break_end_at is not None
    ]
    exit_or_return = [
        e
        for e in a.geofence_events
        if e.event_type in (GeofenceEventType.EXIT, GeofenceEventType.RETURN)
    ]
    return baseline_builder.AttendanceRecord(
        employee_id=a.employee_id,
        check_in_at=a.check_in_at,
        check_out_at=a.check_out_at,
        synthetic_anomaly_type=a.synthetic_anomaly_type,
        breaks=breaks,
        geofence_exit_count=sum(1 for e in a.geofence_events if e.event_type == GeofenceEventType.EXIT),
        geofence_exit_count_anomalous=any(e.synthetic_anomaly_type is not None for e in exit_or_return),
    )


class WorkforceIntelligenceService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._employees = EmployeeRepository(session)
        self._geofences = GeofenceRepository(session)
        self._attendance = AttendanceRepository(session)
        self._breaks = BreakPeriodRepository(session)
        self._geofence_events = GeofenceEventRepository(session)
        self._runs = SyntheticDataRunRepository(session)
        self._baselines = EmployeeBaselineRepository(session)

    async def _resolve_profile(
        self, employee_id: uuid.UUID
    ) -> synthetic_generator.EmployeeProfile:
        employee = await self._employees.get_by_id(employee_id)
        if employee is None:
            raise SyntheticConfigError(f"unknown employee_id: {employee_id}")
        candidates = await self._geofences.list_active_for_employee(
            employee.id, employee.department_id
        )
        if not candidates:
            raise SyntheticConfigError(
                f"employee {employee_id} has no active geofence — nothing to anchor "
                "synthetic check-in locations to"
            )
        # Sorted for determinism (T6): an unordered candidate set would make
        # the same seed pick a different "home" geofence run to run.
        home = min(candidates, key=lambda g: str(g.id))
        if home.center_latitude is None or home.center_longitude is None:
            raise SyntheticConfigError(
                f"employee {employee_id}'s only eligible geofence has no center point "
                "(polygon-only geofences aren't supported as a synthetic anchor yet)"
            )
        return synthetic_generator.EmployeeProfile(
            employee_id=employee.id,
            hire_date=employee.hire_date,
            home_latitude=home.center_latitude,
            home_longitude=home.center_longitude,
        )

    async def _persist(
        self, run_id: uuid.UUID, result: "synthetic_generator.GenerationResult"
    ) -> dict:
        attendance_rows = [
            {
                "employee_id": s.employee_id,
                "attendance_date": s.attendance_date,
                "check_in_at": s.check_in_at,
                "check_in_latitude": s.check_in_latitude,
                "check_in_longitude": s.check_in_longitude,
                "check_out_at": s.check_out_at,
                "check_out_latitude": s.check_out_latitude,
                "check_out_longitude": s.check_out_longitude,
                "status": AttendanceStatus(s.status),
                "synthetic_run_id": run_id,
                "synthetic_anomaly_type": s.synthetic_anomaly_type,
            }
            for s in result.sessions
        ]
        attendances = await self._attendance.bulk_create_synthetic(attendance_rows)

        break_rows = []
        geofence_rows = []
        for session, attendance in zip(result.sessions, attendances, strict=True):
            for b in session.breaks:
                break_rows.append(
                    {
                        "attendance_id": attendance.id,
                        "source": BreakSource.MANUAL,
                        "break_start_at": b.break_start_at,
                        "break_end_at": b.break_end_at,
                        "start_latitude": b.start_latitude,
                        "start_longitude": b.start_longitude,
                        "end_latitude": b.end_latitude,
                        "end_longitude": b.end_longitude,
                        "synthetic_run_id": run_id,
                        "synthetic_anomaly_type": b.synthetic_anomaly_type,
                    }
                )
            for e in session.geofence_events:
                geofence_rows.append(
                    {
                        "employee_id": attendance.employee_id,
                        "attendance_id": attendance.id,
                        "geofence_id": None,
                        "event_type": GeofenceEventType(e.event_type),
                        "latitude": e.latitude,
                        "longitude": e.longitude,
                        "created_at": e.occurred_at,
                        "synthetic_run_id": run_id,
                        "synthetic_anomaly_type": e.synthetic_anomaly_type,
                    }
                )

        if break_rows:
            await self._breaks.bulk_create_synthetic(break_rows)
        if geofence_rows:
            await self._geofence_events.bulk_create_synthetic(geofence_rows)

        return {
            "attendance": len(attendance_rows),
            "breaks": len(break_rows),
            "geofence_events": len(geofence_rows),
            "anomalies": result.anomaly_counts,
        }

    async def generate_synthetic_data(
        self,
        *,
        requested_by: uuid.UUID | None,
        employee_ids: list[uuid.UUID],
        date_range_start: date,
        date_range_end: date,
        anomaly_config: dict,
        seed: int,
    ) -> SyntheticDataRun:
        if not employee_ids:
            raise SyntheticConfigError("employee_scope must not be empty")
        if date_range_end < date_range_start:
            raise SyntheticConfigError("date_range_end must not precede date_range_start")
        # Fail fast on a bad request BEFORE creating a run row — a rejected
        # request should never leave a wasted FAILED row behind.
        config = synthetic_generator.AnomalyConfig.from_dict(anomaly_config)
        profiles = [await self._resolve_profile(employee_id) for employee_id in employee_ids]

        # T13: a synthetic "forgot to check out" row must never collide with
        # a REAL currently-open session on the same employee —
        # uq_attendance_one_open_session is workforce-wide, not scoped to
        # is_synthetic.
        open_employee_ids = frozenset(a.employee_id for a in await self._attendance.list_open())

        # This service commits directly, unlike every other service in this
        # codebase (which only flush() and let get_db()'s end-of-request
        # commit own the transaction boundary): get_db() rolls back the
        # ENTIRE request transaction on any exception escaping the route, and
        # generate_synthetic_data() is required (T2) to raise on failure
        # while still leaving SyntheticDataRun.status == FAILED durably
        # committed. A single request-scoped transaction can't satisfy both,
        # so status transitions are committed as their own small
        # transactions; only the row-generation batch itself is wrapped in a
        # SAVEPOINT (below) so partial rows never survive a mid-batch error.
        run = await self._runs.create(
            requested_by=requested_by,
            employee_scope=[str(e) for e in employee_ids],
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            anomaly_config=anomaly_config,
        )
        await self._runs.set_status(run, SyntheticDataRunStatus.RUNNING)
        await self._session.commit()

        try:
            # T2: the whole batch write is one nested transaction (SAVEPOINT)
            # — any exception rolls back every row this run wrote, so a
            # process kill or a mid-batch error never leaves partial,
            # untagged-consistently rows behind. The outer session (and the
            # RUNNING status already committed above) survives the rollback.
            async with self._session.begin_nested():
                result = synthetic_generator.generate(
                    profiles=profiles,
                    date_range_start=date_range_start,
                    date_range_end=date_range_end,
                    config=config,
                    seed=seed,
                    employees_with_open_session=open_employee_ids,
                )
                row_counts = await self._persist(run.id, result)
            await self._runs.set_status(
                run, SyntheticDataRunStatus.COMPLETED, row_counts=row_counts
            )
            await self._session.commit()
        except Exception as exc:
            logger.exception("synthetic data generation failed for run %s", run.id)
            await self._runs.set_status(
                run, SyntheticDataRunStatus.FAILED, error_message=str(exc)[:1000]
            )
            await self._session.commit()
            raise SyntheticGenerationError(str(exc)) from exc

        return run

    async def rebuild_baselines(
        self,
        *,
        employee_ids: list[uuid.UUID],
        window_start: date,
        window_end: date,
    ) -> dict:
        """Module 2. No run-tracking row exists for this (unlike Module 1's
        SyntheticDataRun) — each employee's baseline upsert is independent,
        so a per-employee failure just gets skipped rather than needing a
        SAVEPOINT/rollback story. Flushes only; the caller (a route via
        get_db(), or a test) owns the commit, matching this codebase's usual
        convention (unlike generate_synthetic_data above, there's no FAILED
        status that a request-level rollback could wrongly erase)."""
        if not employee_ids:
            raise BaselineConfigError("employee_scope must not be empty")
        if window_end < window_start:
            raise BaselineConfigError("window_end must not precede window_start")

        targets = await self._employees.list_by_ids(employee_ids)
        found_ids = {e.id for e in targets}
        missing = [str(eid) for eid in employee_ids if eid not in found_ids]
        if missing:
            raise BaselineConfigError(f"unknown employee_id(s): {', '.join(missing)}")

        skipped_terminated = [e.id for e in targets if e.status == EmployeeStatus.TERMINATED]
        eligible_targets = [e for e in targets if e.status != EmployeeStatus.TERMINATED]

        # Peer pools (department + company-wide) must reflect the WHOLE
        # active/on-leave workforce, not just the employees this call was
        # asked to (re)build — a 1-employee `employee_ids` request must
        # still see that employee's real department peers, not an
        # artificially-empty pool of one. Same "bounded by realistic
        # headcount, not historical volume" precedent as
        # AttendanceRepository.list_open(). ONE query either way (T7).
        workforce = await self._employees.list_all_active_or_on_leave()
        attendances = await self._attendance.list_for_baseline_including_synthetic(
            [e.id for e in workforce], window_start, window_end
        )
        sessions_by_employee: dict[uuid.UUID, list[baseline_builder.AttendanceRecord]] = {
            e.id: [] for e in workforce
        }
        for a in attendances:
            sessions_by_employee[a.employee_id].append(_to_attendance_record(a))

        department_pools: dict[uuid.UUID, dict[uuid.UUID, list[baseline_builder.AttendanceRecord]]] = {}
        for e in workforce:
            if e.department_id is None:
                continue
            department_pools.setdefault(e.department_id, {})[e.id] = sessions_by_employee[e.id]
        company_wide_pool = sessions_by_employee

        built: list[uuid.UUID] = []
        skipped_insufficient_history: list[uuid.UUID] = []
        computed_at = utcnow()

        for e in eligible_targets:
            try:
                self_baseline = baseline_builder.build_for_employee(
                    e.id, sessions_by_employee[e.id]
                )
            except InsufficientHistoryError as exc:
                logger.info("baseline skipped for employee %s: %s", e.id, exc)
                skipped_insufficient_history.append(e.id)
                continue

            peer_baseline = baseline_builder.build_peer_group(
                e.department_id,
                department_pools.get(e.department_id, {}) if e.department_id else {},
                company_wide_pool,
            )
            metric_stats = baseline_builder.to_metric_stats_json(self_baseline, peer_baseline)
            await self._baselines.upsert(
                employee_id=e.id,
                window_start=window_start,
                window_end=window_end,
                metric_stats=metric_stats,
                computed_at=computed_at,
            )
            built.append(e.id)

        return {
            "built": built,
            "skipped_insufficient_history": skipped_insufficient_history,
            "skipped_terminated": skipped_terminated,
        }
