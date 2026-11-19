from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.growth_repo import GrowthRepository
from app.schemas.common import GrowthPeriodType, MetricStatusType
from app.schemas.growth import (
    PostureGrowthResponse,
    PosturePeriodBucket,
    RunningGrowthResponse,
    RunningPeriodBucket,
)


class GrowthService:
    @staticmethod
    async def get_running_growth(
        db: AsyncSession,
        user_id: UUID,
        period: GrowthPeriodType,
    ) -> RunningGrowthResponse:
        days = 7 if period == GrowthPeriodType.weekly else 30
        now = datetime.now(timezone.utc)
        start_dt = now - timedelta(days=days)

        rows = await GrowthRepository.fetch_running_sessions_since(db, str(user_id), start_dt)
        if not rows:
            return RunningGrowthResponse(period=period, status=MetricStatusType.no_data, buckets=[])

        gps_distances = [float(r["distance_m"]) for r in rows if r["mode"] == "gps" and r["distance_m"] is not None]
        gps_paces = [
            int(r["avg_pace_sec_per_km"]) for r in rows if r["mode"] == "gps" and r["avg_pace_sec_per_km"] is not None
        ]
        diff_counts = {"easy": 0, "moderate": 0, "hard": 0}
        for r in rows:
            d = r["reflection_difficulty"]
            if d in diff_counts:
                diff_counts[d] += 1

        bucket = RunningPeriodBucket(
            period_start=start_dt.date(),
            period_end=now.date(),
            run_count=len(rows),
            goal_completed_count=sum(1 for r in rows if r["completion"] == "goal"),
            total_distance_m=sum(gps_distances) if gps_distances else None,
            total_elapsed_ms=sum(int(r["elapsed_ms"]) for r in rows),
            avg_pace_sec_per_km=round(sum(gps_paces) / len(gps_paces)) if gps_paces else None,
            pace_status=MetricStatusType.valid if gps_paces else MetricStatusType.no_data,
            difficulty_counts=diff_counts,
        )
        return RunningGrowthResponse(period=period, status=MetricStatusType.valid, buckets=[bucket])

    @staticmethod
    async def get_posture_growth(
        db: AsyncSession,
        user_id: UUID,
        period: GrowthPeriodType,
    ) -> PostureGrowthResponse:
        days = 7 if period == GrowthPeriodType.weekly else 30
        now = datetime.now(timezone.utc)
        start_dt = now - timedelta(days=days)

        rows = await GrowthRepository.fetch_posture_reports_since(db, str(user_id), start_dt)
        if not rows:
            return PostureGrowthResponse(period=period, overall_status=MetricStatusType.no_data, buckets=[])

        valid_rows = [r for r in rows if r["posture_status"] == "valid"]
        single_rows = [r for r in rows if r["posture_status"] == "single_foot"]

        gct_l = [int(m["ground_contact_time_left_ms"]) for m in rows if m["ground_contact_time_left_ms"] is not None]
        gct_r = [int(m["ground_contact_time_right_ms"]) for m in rows if m["ground_contact_time_right_ms"] is not None]
        load_l = [float(m["left_load_ratio_pct"]) for m in valid_rows if m["left_load_ratio_pct"] is not None]
        load_r = [float(m["right_load_ratio_pct"]) for m in valid_rows if m["right_load_ratio_pct"] is not None]

        overall_status = (
            MetricStatusType.valid
            if valid_rows
            else (MetricStatusType.single_foot if single_rows else MetricStatusType.insufficient_data)
        )

        bucket = PosturePeriodBucket(
            period_start=start_dt.date(),
            period_end=now.date(),
            valid_session_count=len(valid_rows),
            single_foot_session_count=len(single_rows),
            status=overall_status,
            avg_ground_contact_left_ms=round(sum(gct_l) / len(gct_l)) if gct_l else None,
            avg_ground_contact_right_ms=round(sum(gct_r) / len(gct_r)) if gct_r else None,
            avg_left_load_ratio_pct=round(sum(load_l) / len(load_l), 2) if load_l else None,
            avg_right_load_ratio_pct=round(sum(load_r) / len(load_r), 2) if load_r else None,
            dominant_feedback=[],
        )
        return PostureGrowthResponse(period=period, overall_status=overall_status, buckets=[bucket])
