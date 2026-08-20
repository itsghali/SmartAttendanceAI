"""Daily background job that keeps workforce-intelligence data current for
every active employee — old and new — without an HR/Admin having to
manually trigger the Anomaly Detection page's Admin-actions panel per
employee. In-process APScheduler, not Celery (celery is in requirements.txt
but nothing in this codebase wires up a worker/beat for it): the backend
already runs as a single long-lived Railway container (Dockerfile's CMD is
one uvicorn process), so an extra deployment topology isn't needed for this.

Each run: for every active/on-leave employee, backfill a synthetic
bootstrap corpus if they have zero attendance history yet (real or
synthetic), then rebuild their baseline and run detection over a rolling
window. Safe to re-run on a schedule indefinitely — rebuild_baselines and
run_detection both replace their own prior (employee, window) output rather
than accumulating duplicates (see WorkforceIntelligenceService.run_detection
docstring), and the synthetic backfill only ever fires once per employee,
gated on has_any_for_employee rather than on a date, with an idempotency_key
as a second guard against a concurrent double-fire.
"""

import logging
import uuid
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config.settings import get_settings
from app.core.database import async_session_factory
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.employee_repository import EmployeeRepository
from app.services.notification_service import NotificationService
from app.services.workforce_intelligence_service import (
    SyntheticGenerationError,
    WorkforceIntelligenceService,
)

logger = logging.getLogger("app.workforce_intelligence.scheduler")

ROLLING_WINDOW_DAYS = 90


async def _backfill_employees_with_no_history(
    service: WorkforceIntelligenceService,
    attendance_repo: AttendanceRepository,
    employee_ids: list[uuid.UUID],
    window_start: date,
    window_end: date,
) -> dict:
    # One at a time, not a single batched generate_synthetic_data call:
    # that method resolves every employee's anchor geofence up front and
    # raises on the first one that doesn't have one (e.g. a brand-new
    # employee not yet assigned to a geofence), which would abort backfill
    # for the whole batch instead of just that employee.
    backfilled: list[uuid.UUID] = []
    skipped: list[uuid.UUID] = []
    for employee_id in employee_ids:
        if await attendance_repo.has_any_for_employee(employee_id):
            continue
        try:
            await service.generate_synthetic_data(
                requested_by=None,
                employee_ids=[employee_id],
                date_range_start=window_start,
                date_range_end=window_end,
                anomaly_config={},
                seed=employee_id.int % 1_000_000,
                idempotency_key=f"auto-backfill:{employee_id}",
            )
            backfilled.append(employee_id)
        except SyntheticGenerationError as exc:
            logger.warning("auto-backfill failed for employee %s: %s", employee_id, exc)
            skipped.append(employee_id)
        except Exception as exc:
            # e.g. SyntheticConfigError: no active geofence to anchor to yet.
            logger.warning("auto-backfill skipped for employee %s: %s", employee_id, exc)
            skipped.append(employee_id)
    return {"backfilled": backfilled, "skipped": skipped}


async def run_workforce_intelligence_daily_job() -> None:
    window_end = date.today()
    window_start = window_end - timedelta(days=ROLLING_WINDOW_DAYS)

    async with async_session_factory() as session:
        service = WorkforceIntelligenceService(session)
        employees = EmployeeRepository(session)
        attendance = AttendanceRepository(session)

        workforce = await employees.list_all_active_or_on_leave()
        employee_ids = [e.id for e in workforce]
        if not employee_ids:
            logger.info("workforce-intelligence daily job: no active employees, nothing to do")
            return

        backfill_result = await _backfill_employees_with_no_history(
            service, attendance, employee_ids, window_start, window_end
        )

        rebuild_result = await service.rebuild_baselines(
            employee_ids=employee_ids, window_start=window_start, window_end=window_end
        )
        await session.commit()

        detect_result = await service.run_detection(
            employee_ids=employee_ids, window_start=window_start, window_end=window_end
        )
        await session.commit()

        # Once-daily aggregation send for the MODERATE-severity notifications
        # run_detection just created (HIGH ones already went out immediately,
        # inside run_detection itself) — see NotificationService
        # .send_pending_digests's docstring for why this only runs from the
        # scheduled job, not from an ad-hoc admin-triggered detection run.
        digest_result = await NotificationService(session).send_pending_digests()
        await session.commit()

    logger.info(
        "workforce-intelligence daily job done: %d active employees, "
        "backfilled=%d skipped=%d, baselines built=%d "
        "skipped_insufficient_history=%d, detection scored=%d "
        "skipped_no_baseline=%d, total flags=%d, "
        "digest emails sent=%d covering %d notification(s)",
        len(employee_ids),
        len(backfill_result["backfilled"]),
        len(backfill_result["skipped"]),
        len(rebuild_result["built"]),
        len(rebuild_result["skipped_insufficient_history"]),
        len(detect_result["scored"]),
        len(detect_result["skipped_no_baseline"]),
        sum(detect_result["flag_counts"].values()),
        digest_result["recipients"],
        digest_result["notifications"],
    )


def start_scheduler() -> AsyncIOScheduler | None:
    settings = get_settings()
    if not settings.workforce_intelligence_auto_schedule:
        logger.info("workforce-intelligence scheduler disabled via settings")
        return None

    async def _job() -> None:
        try:
            await run_workforce_intelligence_daily_job()
        except Exception:
            # A failed run must not crash the scheduler thread — it should
            # simply try again at the next scheduled fire.
            logger.exception("workforce-intelligence daily job failed")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _job,
        CronTrigger(hour=settings.workforce_intelligence_schedule_hour_utc, minute=0),
        id="workforce_intelligence_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info(
        "workforce-intelligence scheduler started: daily at %02d:00 UTC",
        settings.workforce_intelligence_schedule_hour_utc,
    )
    return scheduler
