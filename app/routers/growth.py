from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import AuthenticatedUser, get_current_user
from app.schemas.common import GrowthPeriodType, MetricStatusType
from app.schemas.growth import (
    PostureGrowthResponse,
    PosturePeriodBucket,
    RunningGrowthResponse,
    RunningPeriodBucket,
)

KST = ZoneInfo("Asia/Seoul")
router = APIRouter(prefix="/api/v1/growth", tags=["Growth"])


def _build_calendar_ranges(now_kst: datetime, period: GrowthPeriodType) -> list[tuple[date, date]]:
    """
    KST 달력 기준 버킷 구간 생성:
    - weekly: 이번 주(월~일)와 직전 주(월~일) 2개 버킷 (최근 주 vs 이전 주 비교 지원)
    - monthly: 이번 달 1일부터 현재 주까지 월요일 시작 주차별 버킷 배열
    """
    today = now_kst.date()
    this_monday = today - timedelta(days=today.weekday())
    if period == GrowthPeriodType.weekly:
        prev_monday = this_monday - timedelta(days=7)
        return [
            (prev_monday, prev_monday + timedelta(days=6)),
            (this_monday, this_monday + timedelta(days=6)),
        ]

    first_day = today.replace(day=1)
    first_monday = first_day - timedelta(days=first_day.weekday())
    ranges: list[tuple[date, date]] = []
    curr = first_monday
    while curr <= this_monday:
        start_d = max(curr, first_day)
        end_d = curr + timedelta(days=6)
        ranges.append((start_d, end_d))
        curr += timedelta(days=7)
    return ranges


@router.get("/running", response_model=RunningGrowthResponse)
async def get_running_growth(
    period: GrowthPeriodType = Query(default=GrowthPeriodType.weekly),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> RunningGrowthResponse:
    now_kst = datetime.now(KST)
    ranges = _build_calendar_ranges(now_kst, period)
    earliest_kst = datetime.combine(ranges[0][0], datetime.min.time(), tzinfo=KST)

    rows = (
        await db.execute(
            text(
                """
                SELECT started_at, mode, completion, distance_m, elapsed_ms,
                       avg_pace_sec_per_km, reflection_difficulty
                FROM public.run_sessions
                WHERE user_id = :uid
                  AND started_at >= :earliest_kst
                  AND started_at <= :now_kst
                ORDER BY started_at ASC
                """
            ),
            {"uid": str(user.user_id), "earliest_kst": earliest_kst, "now_kst": now_kst},
        )
    ).fetchall()

    if not rows:
        return RunningGrowthResponse(period=period, status=MetricStatusType.no_data, buckets=[])

    buckets: list[RunningPeriodBucket] = []
    for start_d, end_d in ranges:
        in_bucket = [
            r._mapping
            for r in rows
            if start_d <= r._mapping["started_at"].astimezone(KST).date() <= end_d
        ]
        gps_rows = [
            m for m in in_bucket
            if m["mode"] == "gps" and m["distance_m"] is not None and float(m["distance_m"]) > 0
        ]
        total_dist_m = sum(float(m["distance_m"]) for m in gps_rows) if gps_rows else None
        total_elapsed_ms = sum(int(m["elapsed_ms"]) for m in in_bucket) if in_bucket else None

        # 거리 가중 평균 페이스 (총 GPS 시간(초) / 총 GPS 거리(km))
        weighted_pace: int | None = None
        if total_dist_m and total_dist_m > 0:
            gps_elapsed_sec = sum(int(m["elapsed_ms"]) for m in gps_rows) / 1000.0
            weighted_pace = round(gps_elapsed_sec / (total_dist_m / 1000.0))

        diff_counts = {"easy": 0, "moderate": 0, "hard": 0}
        for m in in_bucket:
            d = m["reflection_difficulty"]
            if d in diff_counts:
                diff_counts[d] += 1

        buckets.append(
            RunningPeriodBucket(
                period_start=start_d,
                period_end=end_d,
                run_count=len(in_bucket),
                goal_completed_count=sum(1 for m in in_bucket if m["completion"] == "goal"),
                total_distance_m=total_dist_m,
                total_elapsed_ms=total_elapsed_ms,
                avg_pace_sec_per_km=weighted_pace,
                pace_status=MetricStatusType.valid if weighted_pace is not None else MetricStatusType.no_data,
                difficulty_counts=diff_counts,
            )
        )

    has_any = any(b.run_count > 0 for b in buckets)
    return RunningGrowthResponse(
        period=period,
        status=MetricStatusType.valid if has_any else MetricStatusType.no_data,
        buckets=buckets,
    )


@router.get("/posture", response_model=PostureGrowthResponse)
async def get_posture_growth(
    period: GrowthPeriodType = Query(default=GrowthPeriodType.weekly),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> PostureGrowthResponse:
    now_kst = datetime.now(KST)
    ranges = _build_calendar_ranges(now_kst, period)
    earliest_kst = datetime.combine(ranges[0][0], datetime.min.time(), tzinfo=KST)

    rows = (
        await db.execute(
            text(
                """
                SELECT s.started_at,
                       p.posture_status,
                       p.ground_contact_time_left_ms,
                       p.ground_contact_time_right_ms,
                       p.left_load_ratio_pct,
                       p.right_load_ratio_pct,
                       p.feedback_items
                FROM public.run_posture_reports p
                JOIN public.run_sessions s ON s.id = p.run_id
                WHERE p.user_id = :uid
                  AND s.started_at >= :earliest_kst
                  AND s.started_at <= :now_kst
                ORDER BY s.started_at ASC
                """
            ),
            {"uid": str(user.user_id), "earliest_kst": earliest_kst, "now_kst": now_kst},
        )
    ).fetchall()

    if not rows:
        return PostureGrowthResponse(period=period, overall_status=MetricStatusType.no_data, buckets=[])

    buckets: list[PosturePeriodBucket] = []
    for start_d, end_d in ranges:
        in_bucket = [
            r._mapping
            for r in rows
            if start_d <= r._mapping["started_at"].astimezone(KST).date() <= end_d
        ]
        valid_rows = [m for m in in_bucket if m["posture_status"] == "valid"]
        single_rows = [m for m in in_bucket if m["posture_status"] == "single_foot"]

        gct_l = [int(m["ground_contact_time_left_ms"]) for m in in_bucket if m["ground_contact_time_left_ms"] is not None]
        gct_r = [int(m["ground_contact_time_right_ms"]) for m in in_bucket if m["ground_contact_time_right_ms"] is not None]
        load_l = [float(m["left_load_ratio_pct"]) for m in valid_rows if m["left_load_ratio_pct"] is not None]
        load_r = [float(m["right_load_ratio_pct"]) for m in valid_rows if m["right_load_ratio_pct"] is not None]

        fb_counter: Counter[str] = Counter()
        for m in in_bucket:
            for item in (m["feedback_items"] or []):
                if isinstance(item, str) and item:
                    fb_counter[item] += 1

        b_status = (
            MetricStatusType.valid
            if valid_rows
            else (MetricStatusType.single_foot if single_rows else MetricStatusType.no_data)
        )
        buckets.append(
            PosturePeriodBucket(
                period_start=start_d,
                period_end=end_d,
                valid_session_count=len(valid_rows),
                single_foot_session_count=len(single_rows),
                status=b_status,
                avg_ground_contact_left_ms=round(sum(gct_l) / len(gct_l)) if gct_l else None,
                avg_ground_contact_right_ms=round(sum(gct_r) / len(gct_r)) if gct_r else None,
                avg_left_load_ratio_pct=round(sum(load_l) / len(load_l), 2) if load_l else None,
                avg_right_load_ratio_pct=round(sum(load_r) / len(load_r), 2) if load_r else None,
                dominant_feedback=[k for k, _ in fb_counter.most_common(3)],
            )
        )

    any_valid = any(b.valid_session_count > 0 for b in buckets)
    any_single = any(b.single_foot_session_count > 0 for b in buckets)
    overall = (
        MetricStatusType.valid
        if any_valid
        else (MetricStatusType.single_foot if any_single else MetricStatusType.insufficient_data)
    )
    return PostureGrowthResponse(period=period, overall_status=overall, buckets=buckets)
