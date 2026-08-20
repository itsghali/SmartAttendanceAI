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

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import Coordinates, haversine_distance_meters
from app.models.attendance import Attendance, AttendanceStatus
from app.models.break_period import BreakSource
from app.models.employee import EmployeeStatus
from app.models.employee_baseline import EmployeeBaseline
from app.models.employee_deviation_flag import DeviationSeverity, EmployeeDeviationFlag, ReviewStatus
from app.models.geofence_event import GeofenceEventType
from app.models.mixins import utcnow
from app.models.synthetic_data_run import SyntheticDataRun, SyntheticDataRunStatus
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.break_period_repository import BreakPeriodRepository
from app.repositories.employee_baseline_repository import EmployeeBaselineRepository
from app.repositories.employee_deviation_flag_repository import EmployeeDeviationFlagRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.geofence_event_repository import GeofenceEventRepository
from app.repositories.geofence_repository import GeofenceRepository
from app.repositories.impossible_travel_rejection_repository import (
    ImpossibleTravelRejectionRepository,
)
from app.repositories.synthetic_data_run_repository import SyntheticDataRunRepository
from app.services.notification_service import NotificationService

_AI_DIR = Path(__file__).resolve().parents[3] / "ai"
if str(_AI_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_DIR))

from workforce_intelligence.baseline import builder as baseline_builder  # noqa: E402
from workforce_intelligence.detection import detector  # noqa: E402
from workforce_intelligence.exceptions import (  # noqa: E402
    BaselineConfigError,
    DetectionConfigError,
    InsufficientHistoryError,
    SyntheticConfigError,
)
from workforce_intelligence.insights import generator as insights_generator  # noqa: E402
from workforce_intelligence.synthetic import generator as synthetic_generator  # noqa: E402

logger = logging.getLogger("app.workforce_intelligence")


class SyntheticGenerationError(Exception):
    """Raised after a SyntheticDataRun has already been recorded FAILED
    (PLAN.md T2) — the run row's error_message carries the real detail; this
    is just the signal to the caller that the request did not complete.
    Carries the FAILED run itself (not just its message) so a route-layer
    caller can still return the run's id/status to the client rather than
    losing that context behind a bare exception."""

    def __init__(self, message: str, run: SyntheticDataRun):
        super().__init__(message)
        self.run = run


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
    checkout_distance_from_checkin_km = None
    if (
        a.check_in_latitude is not None
        and a.check_in_longitude is not None
        and a.check_out_latitude is not None
        and a.check_out_longitude is not None
    ):
        checkout_distance_from_checkin_km = (
            haversine_distance_meters(
                Coordinates(a.check_in_latitude, a.check_in_longitude),
                Coordinates(a.check_out_latitude, a.check_out_longitude),
            )
            / 1000
        )
    return baseline_builder.AttendanceRecord(
        employee_id=a.employee_id,
        check_in_at=a.check_in_at,
        check_out_at=a.check_out_at,
        synthetic_anomaly_type=a.synthetic_anomaly_type,
        breaks=breaks,
        geofence_exit_count=sum(1 for e in a.geofence_events if e.event_type == GeofenceEventType.EXIT),
        geofence_exit_count_anomalous=any(e.synthetic_anomaly_type is not None for e in exit_or_return),
        is_synthetic=a.is_synthetic,
        synthetic_run_id=a.synthetic_run_id,
        attendance_id=a.id,
        checkout_distance_from_checkin_km=checkout_distance_from_checkin_km,
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
        self._deviation_flags = EmployeeDeviationFlagRepository(session)
        self._rejections = ImpossibleTravelRejectionRepository(session)

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
        idempotency_key: str | None = None,
    ) -> SyntheticDataRun:
        if not employee_ids:
            raise SyntheticConfigError("employee_scope must not be empty")
        if date_range_end < date_range_start:
            raise SyntheticConfigError("date_range_end must not precede date_range_start")

        # T10: a client-supplied idempotency key short-circuits to the
        # existing run (whatever its outcome) instead of regenerating —
        # a retried/double-fired request with the same key never produces a
        # second corpus.
        if idempotency_key is not None:
            existing = await self._runs.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

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
        try:
            run = await self._runs.create(
                requested_by=requested_by,
                employee_scope=[str(e) for e in employee_ids],
                date_range_start=date_range_start,
                date_range_end=date_range_end,
                anomaly_config=anomaly_config,
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            # Race: two concurrent requests both passed the pre-check above
            # with the same idempotency_key. Whichever loses the unique-
            # constraint race reuses the winner's run instead of erroring.
            await self._session.rollback()
            assert idempotency_key is not None  # only a key collision raises this
            winner = await self._runs.get_by_idempotency_key(idempotency_key)
            assert winner is not None
            return winner
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
            raise SyntheticGenerationError(str(exc), run=run) from exc

        return run

    async def get_synthetic_run(self, run_id: uuid.UUID) -> SyntheticDataRun | None:
        return await self._runs.get_by_id(run_id)

    async def get_baseline(self, employee_id: uuid.UUID) -> EmployeeBaseline | None:
        return await self._baselines.get_by_employee_id(employee_id)

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

    async def run_detection(
        self,
        *,
        employee_ids: list[uuid.UUID],
        window_start: date,
        window_end: date,
    ) -> dict:
        """Module 3. Scores each requested employee's sessions in
        [window_start, window_end] against their EXISTING EmployeeBaseline
        (built separately by rebuild_baselines) — detection does not build
        or require a baseline whose own window matches this one; scoring a
        more recent window against an older baseline is the
        production-realistic case, this pass's fixture-validation tests
        happen to use the same window for both. An employee with no
        baseline yet is skipped, not an error — same "per-employee skip,
        not whole-batch abort" posture as skipped_insufficient_history in
        rebuild_baselines above.

        Flushes only (no run-tracking row, no FAILED-status durability
        problem) — same convention as rebuild_baselines: each employee's
        flag-set replacement is independent, a per-employee failure doesn't
        need a SAVEPOINT/rollback story."""
        if not employee_ids:
            raise DetectionConfigError("employee_scope must not be empty")
        if window_end < window_start:
            raise DetectionConfigError("window_end must not precede window_start")

        targets = await self._employees.list_by_ids(employee_ids)
        found_ids = {e.id for e in targets}
        missing = [str(eid) for eid in employee_ids if eid not in found_ids]
        if missing:
            raise DetectionConfigError(f"unknown employee_id(s): {', '.join(missing)}")

        attendances = await self._attendance.list_for_baseline_including_synthetic(
            [e.id for e in targets], window_start, window_end
        )
        sessions_by_employee: dict[uuid.UUID, list[baseline_builder.AttendanceRecord]] = {
            e.id: [] for e in targets
        }
        for a in attendances:
            sessions_by_employee[a.employee_id].append(_to_attendance_record(a))

        scored: list[uuid.UUID] = []
        skipped_no_baseline: list[uuid.UUID] = []
        flag_counts: dict[str, int] = {}
        new_flag_rows: list[EmployeeDeviationFlag] = []
        detected_at = utcnow()

        for e in targets:
            baseline = await self._baselines.get_by_employee_id(e.id)
            if baseline is None:
                skipped_no_baseline.append(e.id)
                continue

            self_metrics = {
                metric: baseline_builder.MetricStats(**baseline.metric_stats[metric]["self"])
                for metric in baseline_builder.METRICS
            }
            # peer's stored shape carries extra "source"/"department_id"
            # keys (see to_metric_stats_json) that MetricStats doesn't
            # accept — pull only the 3 stat fields, not **-unpack the dict.
            peer_metrics = {
                metric: baseline_builder.MetricStats(
                    mean=baseline.metric_stats[metric]["peer"]["mean"],
                    std=baseline.metric_stats[metric]["peer"]["std"],
                    n=baseline.metric_stats[metric]["peer"]["n"],
                )
                for metric in baseline_builder.METRICS
            }

            flags = detector.detect_for_employee(
                sessions_by_employee[e.id], self_metrics, peer_metrics
            )

            # Idempotent rebuild semantics: a re-run for this exact
            # (employee, window) replaces its own prior flags rather than
            # accumulating duplicates on every trigger.
            await self._deviation_flags.delete_for_employee_window(e.id, window_start, window_end)
            if flags:
                rows = [
                    {
                        "employee_id": f.employee_id,
                        "attendance_id": f.attendance_id,
                        "metric": f.metric,
                        "occurred_at": f.occurred_at,
                        "observed_value": f.observed_value,
                        "self_mean": f.self_mean,
                        "self_std": f.self_std,
                        "self_z": f.self_z,
                        "self_n": f.self_n,
                        "peer_mean": f.peer_mean,
                        "peer_std": f.peer_std,
                        "peer_z": f.peer_z,
                        "peer_n": f.peer_n,
                        "severity": DeviationSeverity(f.severity),
                        "window_start": window_start,
                        "window_end": window_end,
                        "detected_at": detected_at,
                        "is_synthetic": f.is_synthetic,
                        "synthetic_run_id": f.synthetic_run_id,
                        "synthetic_anomaly_type": f.synthetic_anomaly_type,
                    }
                    for f in flags
                ]
                created_rows = await self._deviation_flags.bulk_create(rows)
                # Synthetic flags never reach a real HR/Admin notification —
                # same "excluded from any real-employee-facing read path by
                # default" rule EmployeeDeviationFlag's own docstring states
                # for is_synthetic rows generally.
                new_flag_rows.extend(r for r in created_rows if not r.is_synthetic)
            scored.append(e.id)
            flag_counts[str(e.id)] = len(flags)

        if new_flag_rows:
            notification_service = NotificationService(self._session)
            await notification_service.notify_new_flags(
                new_flag_rows, {e.id: e for e in targets}
            )

        return {
            "scored": scored,
            "skipped_no_baseline": skipped_no_baseline,
            "flag_counts": flag_counts,
        }

    async def list_deviation_flags(
        self,
        employee_id: uuid.UUID | None,
        window_start: date | None,
        window_end: date | None,
        limit: int,
        offset: int,
    ):
        return await self._deviation_flags.list_paginated(
            employee_id, window_start, window_end, limit, offset
        )

    async def list_impossible_travel_rejections(
        self,
        employee_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        limit: int,
        offset: int,
    ):
        return await self._rejections.list_paginated(
            employee_id, date_from, date_to, limit, offset
        )

    async def list_insights(
        self,
        employee_id: uuid.UUID | None,
        window_start: date | None,
        window_end: date | None,
        review_status: ReviewStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[EmployeeDeviationFlag, dict]], int]:
        """Module 4. Evidence threshold (PLAN.md CEO-phase review, Hour 1):
        HIGH severity only — MODERATE flags stay structured-only in the
        existing /detection/flags evidence view, not promoted to prose,
        while the underlying z-score thresholds remain untuned against real
        data (TODOS.md).

        Returns the Requirement-2 presentation dict (title/summary/
        explanation/evidence/technical/recommended_action) per flag, same
        shape NotificationService.notify_new_flags builds off the live flag
        row — see insights/generator.py's build_presentation."""
        items, total = await self._deviation_flags.list_paginated(
            employee_id,
            window_start,
            window_end,
            limit,
            offset,
            severity=DeviationSeverity.HIGH,
            review_status=review_status,
        )
        presented = [
            (
                flag,
                insights_generator.build_presentation(
                    metric=flag.metric,
                    observed_value=flag.observed_value,
                    self_mean=flag.self_mean,
                    self_std=flag.self_std,
                    self_z=flag.self_z,
                    self_n=flag.self_n,
                    peer_mean=flag.peer_mean,
                    peer_std=flag.peer_std,
                    peer_z=flag.peer_z,
                    peer_n=flag.peer_n,
                    severity=flag.severity.value,
                    occurred_at=flag.occurred_at,
                    detected_at=flag.detected_at,
                ),
            )
            for flag in items
        ]
        return presented, total

    async def review_flag(
        self, flag_id: uuid.UUID, status: ReviewStatus, reviewer_id: uuid.UUID | None
    ) -> EmployeeDeviationFlag | None:
        flag = await self._deviation_flags.get_by_id(flag_id)
        if flag is None:
            return None
        return await self._deviation_flags.set_review_status(
            flag, status, reviewer_id, utcnow()
        )
