from datetime import datetime
from typing import List
from uuid import UUID
from pydantic import BaseModel
from app.schemas.common import MetricStatusType, RunCompletionType


class WeeklyActivitySummary(BaseModel):
    # 월요일(0) ~ 일요일(6) 달린 날 표시 배열
    run_days: List[bool]
    run_count: int
    # TIME 전용 러닝만 있으면 distance_m이 없으므로 0이 아닌 None 또는 유효 GPS 거리 합계만 반환
    total_gps_distance_m: float | None
    total_elapsed_ms: int


class LastRunBrief(BaseModel):
    run_id: UUID
    started_at: datetime
    completion: RunCompletionType
    distance_m: float | None
    elapsed_ms: int
    avg_pace_sec_per_km: int | None


class RecommendedGoalView(BaseModel):
    distance_km: float
    target_duration_sec: int
    target_pace_sec_per_km: int
    basis_type: str  # "recent_runs" | "baseline" | "onboarding" | "default_starter"
    basis_description: str
    display_pace_sec_per_km: int | None = None
    warmup_pace_sec_per_km: int | None = None
    rhythm_pace_sec_per_km: int | None = None
    realtime_initial_pace_sec_per_km: int | None = None


class HomeSummaryResponse(BaseModel):
    weekly_activity: WeeklyActivitySummary
    last_run: LastRunBrief | None
    recommended_goal: RecommendedGoalView
    should_prompt_baseline: bool
    baseline_status: MetricStatusType
