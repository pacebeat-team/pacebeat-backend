from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import AuthenticatedUser, get_current_user
from app.schemas.common import MetricStatusType
from app.schemas.home import (
    HomeSummaryResponse,
    LastRunBrief,
    WeeklyActivitySummary,
)
from app.services.recommendation_service import RecommendationService

KST = ZoneInfo("Asia/Seoul")
router = APIRouter(prefix="/api/v1/home", tags=["Home"])


@router.get("/summary", response_model=HomeSummaryResponse)
async def get_home_summary(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> HomeSummaryResponse:
    uid = str(user.user_id)
    now_kst = datetime.now(KST)
    # KST 기준 이번 주 월요일 00:00:00 ~ 다음 주 월요일 00:00:00
    monday_kst = (now_kst - timedelta(days=now_kst.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    next_monday_kst = monday_kst + timedelta(days=7)

    week_rows = (
        await db.execute(
            text(
                """
                SELECT started_at, mode, distance_m, elapsed_ms
                FROM public.run_sessions
                WHERE user_id = :uid
                  AND started_at >= :monday_kst
                  AND started_at < :next_monday_kst
                  AND started_at <= :now_kst
                ORDER BY started_at DESC
                """
            ),
            {
                "uid": uid,
                "monday_kst": monday_kst,
                "next_monday_kst": next_monday_kst,
                "now_kst": now_kst,
            },
        )
    ).fetchall()

    run_days = [False] * 7
    gps_distances: list[float] = []
    total_elapsed_ms = 0
    for r in week_rows:
        m = r._mapping
        started_kst = m["started_at"].astimezone(KST)
        run_days[started_kst.weekday()] = True
        total_elapsed_ms += int(m["elapsed_ms"])
        if m["mode"] == "gps" and m["distance_m"] is not None:
            gps_distances.append(float(m["distance_m"]))

    last_row = (
        await db.execute(
            text(
                """
                SELECT id, started_at, completion, distance_m, elapsed_ms, avg_pace_sec_per_km
                FROM public.run_sessions
                WHERE user_id = :uid AND started_at <= :now_kst
                ORDER BY started_at DESC
                LIMIT 1
                """
            ),
            {"uid": uid, "now_kst": now_kst},
        )
    ).first()

    last_run = (
        LastRunBrief(
            run_id=last_row._mapping["id"],
            started_at=last_row._mapping["started_at"],
            completion=last_row._mapping["completion"],
            distance_m=float(last_row._mapping["distance_m"])
            if last_row._mapping["distance_m"] is not None
            else None,
            elapsed_ms=last_row._mapping["elapsed_ms"],
            avg_pace_sec_per_km=last_row._mapping["avg_pace_sec_per_km"],
        )
        if last_row
        else None
    )

    recommended, baseline_status = await RecommendationService.get_recommended_goal(
        db=db,
        user_id=user.user_id,
        now_kst=now_kst,
    )

    return HomeSummaryResponse(
        weekly_activity=WeeklyActivitySummary(
            run_days=run_days,
            run_count=len(week_rows),
            total_gps_distance_m=sum(gps_distances) if gps_distances else None,
            total_elapsed_ms=total_elapsed_ms,
        ),
        last_run=last_run,
        recommended_goal=recommended,
        should_prompt_baseline=(baseline_status != MetricStatusType.valid),
        baseline_status=baseline_status,
    )
