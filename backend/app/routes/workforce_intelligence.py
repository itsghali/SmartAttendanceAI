"""HR/Admin-facing API surface for Module 1 (synthetic data generation),
Module 2 (per-employee/peer-group baselines), Module 3 (deviation detection
+ the impossible-travel-rejection audit trail), and Module 4 (insight
prose + reviewer-action state) — see PLAN.md.

Execution model (T11): every trigger endpoint below is synchronous/blocking
— the request does not return until WorkforceIntelligenceService has fully
completed (or failed) the batch, matching the service's own blocking design
(no FastAPI BackgroundTasks, no scheduler). There is deliberately no
"returns run_id immediately, client polls" flow here: the POST response IS
the finished (or failed) result. If the process crashes mid-request, a
RUNNING SyntheticDataRun row is left orphaned with no automatic reconciler —
this ties to the plan's existing no-scheduler decision (0D-POST) and is not
fixed here.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, require_permission
from app.models.employee_deviation_flag import ReviewStatus
from app.models.user import User
from app.schemas.workforce_intelligence import (
    BaselineRebuildRequest,
    BaselineRebuildResultOut,
    DetectionRunRequest,
    DetectionRunResultOut,
    EmployeeBaselineOut,
    EmployeeDeviationFlagListOut,
    EmployeeDeviationFlagOut,
    ImpossibleTravelRejectionListOut,
    ReviewFlagRequest,
    SyntheticDataGenerateRequest,
    SyntheticDataRunOut,
    WorkforceInsightListOut,
    WorkforceInsightOut,
)
from app.services.workforce_intelligence_service import (
    SyntheticGenerationError,
    WorkforceIntelligenceService,
)

# workforce_intelligence_service (imported above) already does the
# sys.path injection for ai/workforce_intelligence at its own module load
# time (mirrors face_service.py's existing precedent), so this import is
# safe here.
from workforce_intelligence.exceptions import (  # noqa: E402
    BaselineConfigError,
    DetectionConfigError,
    SyntheticConfigError,
)

router = APIRouter(prefix="/workforce-intelligence", tags=["workforce-intelligence"])


@router.post(
    "/synthetic-data/generate",
    response_model=SyntheticDataRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("workforce_intelligence:write"))],
)
async def generate_synthetic_data(
    body: SyntheticDataGenerateRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SyntheticDataRunOut:
    service = WorkforceIntelligenceService(session)
    try:
        run = await service.generate_synthetic_data(
            requested_by=user.id,
            employee_ids=body.employee_ids,
            date_range_start=body.date_range_start,
            date_range_end=body.date_range_end,
            anomaly_config=body.anomaly_config,
            seed=body.seed,
            idempotency_key=body.idempotency_key,
        )
    except SyntheticConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SyntheticGenerationError as exc:
        # Already recorded FAILED durably (PLAN.md T2/Section 2) — surface
        # the run as-is rather than a bare 500; the client sees status=
        # "failed" + error_message on an otherwise normal response.
        run = exc.run
    return SyntheticDataRunOut.model_validate(run)


@router.get(
    "/synthetic-data/{run_id}",
    response_model=SyntheticDataRunOut,
    dependencies=[Depends(require_permission("workforce_intelligence:read"))],
)
async def get_synthetic_run(
    run_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> SyntheticDataRunOut:
    run = await WorkforceIntelligenceService(session).get_synthetic_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return SyntheticDataRunOut.model_validate(run)


@router.post(
    "/baselines/rebuild",
    response_model=BaselineRebuildResultOut,
    dependencies=[Depends(require_permission("workforce_intelligence:write"))],
)
async def rebuild_baselines(
    body: BaselineRebuildRequest, session: AsyncSession = Depends(get_db)
) -> BaselineRebuildResultOut:
    service = WorkforceIntelligenceService(session)
    try:
        result = await service.rebuild_baselines(
            employee_ids=body.employee_ids,
            window_start=body.window_start,
            window_end=body.window_end,
        )
    except BaselineConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BaselineRebuildResultOut(**result)


@router.get(
    "/baselines/{employee_id}",
    response_model=EmployeeBaselineOut,
    dependencies=[Depends(require_permission("workforce_intelligence:read"))],
)
async def get_baseline(
    employee_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> EmployeeBaselineOut:
    baseline = await WorkforceIntelligenceService(session).get_baseline(employee_id)
    if baseline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="baseline not found")
    return EmployeeBaselineOut.model_validate(baseline)


@router.post(
    "/detection/run",
    response_model=DetectionRunResultOut,
    dependencies=[Depends(require_permission("workforce_intelligence:write"))],
)
async def run_detection(
    body: DetectionRunRequest, session: AsyncSession = Depends(get_db)
) -> DetectionRunResultOut:
    service = WorkforceIntelligenceService(session)
    try:
        result = await service.run_detection(
            employee_ids=body.employee_ids,
            window_start=body.window_start,
            window_end=body.window_end,
        )
    except DetectionConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DetectionRunResultOut(**result)


@router.get(
    "/detection/flags",
    response_model=EmployeeDeviationFlagListOut,
    dependencies=[Depends(require_permission("workforce_intelligence:read"))],
)
async def list_deviation_flags(
    employee_id: uuid.UUID | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> EmployeeDeviationFlagListOut:
    items, total = await WorkforceIntelligenceService(session).list_deviation_flags(
        employee_id, window_start, window_end, limit, offset
    )
    return EmployeeDeviationFlagListOut(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/impossible-travel-rejections",
    response_model=ImpossibleTravelRejectionListOut,
    dependencies=[Depends(require_permission("workforce_intelligence:read"))],
)
async def list_impossible_travel_rejections(
    employee_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> ImpossibleTravelRejectionListOut:
    items, total = await WorkforceIntelligenceService(session).list_impossible_travel_rejections(
        employee_id, date_from, date_to, limit, offset
    )
    return ImpossibleTravelRejectionListOut(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/insights",
    response_model=WorkforceInsightListOut,
    dependencies=[Depends(require_permission("workforce_intelligence:read"))],
)
async def list_insights(
    employee_id: uuid.UUID | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
    review_status: ReviewStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> WorkforceInsightListOut:
    items, total = await WorkforceIntelligenceService(session).list_insights(
        employee_id, window_start, window_end, review_status, limit, offset
    )
    return WorkforceInsightListOut(
        items=[
            WorkforceInsightOut(
                **EmployeeDeviationFlagOut.model_validate(flag).model_dump(), summary=summary
            )
            for flag, summary in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/detection/flags/{flag_id}/review",
    response_model=EmployeeDeviationFlagOut,
    dependencies=[Depends(require_permission("workforce_intelligence:write"))],
)
async def review_flag(
    flag_id: uuid.UUID,
    body: ReviewFlagRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> EmployeeDeviationFlagOut:
    flag = await WorkforceIntelligenceService(session).review_flag(flag_id, body.status, user.id)
    if flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="flag not found")
    return EmployeeDeviationFlagOut.model_validate(flag)
