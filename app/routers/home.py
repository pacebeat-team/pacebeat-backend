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
    RecommendedGoalView,
    WeeklyActivitySummary,
)

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

    baseline_row = (
        await db.execute(
            text("SELECT quality_status, baseline_pace_sec_per_km FROM public.user_baselines WHERE user_id = :uid"),
            {"uid": uid},
        )
    ).first()

    baseline_status = (
        MetricStatusType(baseline_row._mapping["quality_status"])
        if baseline_row
        else MetricStatusType.no_data
    )
    baseline_pace = baseline_row._mapping["baseline_pace_sec_per_km"] if baseline_row else None

    if baseline_status == MetricStatusType.valid and baseline_pace:
        pace = int(baseline_pace)
        recommended = RecommendedGoalView(
            distance_km=3.0,
            target_duration_sec=pace * 3,
            target_pace_sec_per_km=pace,
            basis_type="baseline",
            basis_description="기초 측정 기준 페이스를 바탕으로 설정된 목표입니다.",
        )
    else:
        recommended = RecommendedGoalView(
            distance_km=3.0,
            target_duration_sec=1260,
            target_pace_sec_per_km=420,
            basis_type="default_starter",
            basis_description="누구나 부담 없이 시작할 수 있는 기본 3.0 km 목표입니다.",
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
