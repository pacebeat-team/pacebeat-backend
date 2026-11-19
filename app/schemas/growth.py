from datetime import date
from typing import Dict, List
from pydantic import BaseModel
from app.schemas.common import GrowthPeriodType, MetricStatusType


class RunningPeriodBucket(BaseModel):
    period_start: date
    period_end: date
    run_count: int
    goal_completed_count: int
    # GPS 러닝이 없는 기간은 0으로 채우지 않고 None 반환
    total_distance_m: float | None
    total_elapsed_ms: int | None
    avg_pace_sec_per_km: int | None
    pace_status: MetricStatusType
    difficulty_counts: Dict[str, int]


class RunningGrowthResponse(BaseModel):
    period: GrowthPeriodType
    status: MetricStatusType
    buckets: List[RunningPeriodBucket]


class PosturePeriodBucket(BaseModel):
    period_start: date
    period_end: date
    valid_session_count: int
    single_foot_session_count: int
    status: MetricStatusType
    avg_ground_contact_left_ms: int | None
    avg_ground_contact_right_ms: int | None
    avg_left_load_ratio_pct: float | None
    avg_right_load_ratio_pct: float | None
    dominant_feedback: List[str]


class PostureGrowthResponse(BaseModel):
    period: GrowthPeriodType
    # 인솔 미구매·미연결 또는 유효 세션 0건일 때 "no_data" / "insufficient_data" 반환 (점수 추정 금지)
    overall_status: MetricStatusType
    buckets: List[PosturePeriodBucket]
