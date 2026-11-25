from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.common import MetricStatusType
from app.schemas.home import RecommendedGoalView

KST = ZoneInfo("Asia/Seoul")

RECOMMENDED_DISTANCE_KM = 3.0
MIN_PACE_SEC_PER_KM = 240
MAX_PACE_SEC_PER_KM = 600
DEFAULT_STARTER_PACE_SEC_PER_KM = 420

WARMUP_PACE_FACTOR = 1.05
RHYTHM_PACE_FACTOR = (0.85 - 0.1575) / 0.70  # 0.6925 / 0.70 ≈ 0.9892857
REALTIME_INITIAL_PACE_FACTOR = 0.95

# 온보딩 9가지 조합 기준 페이스 (sec/km)
ONBOARDING_PACE_TABLE: dict[str, dict[str, int]] = {
    "beginner": {"1": 480, "2": 465, "3+": 450},
    "occasional": {"1": 435, "2": 420, "3+": 405},
    "regular": {"1": 405, "2": 390, "3+": 375},
}


@dataclass(frozen=True)
class SegmentPaces:
    warmup_pace_sec_per_km: int
    rhythm_pace_sec_per_km: int
    realtime_initial_pace_sec_per_km: int


@dataclass(frozen=True)
class RealtimePaceResult:
    required_pace_sec_per_km: int
    guidance_mode: str  # "warmup" | "rhythm" | "realtime" | "realtime_frozen" | "completion_first"
    early_arrival_sec: float
    is_frozen: bool


def round_half_up_int(value: float) -> int:
    return int(math.floor(value + 0.5))


def round_pace_5s(pace_sec: float) -> int:
    """화면 표시용 5초 단위 사사오입 반올림"""
    return int(math.floor(pace_sec / 5.0 + 0.5)) * 5


def clamp_pace(pace_sec: float) -> int:
    """허용 페이스 범위(240초 ~ 600초, 경계값 포함)로 클램핑"""
    rounded = round_half_up_int(pace_sec)
    return max(MIN_PACE_SEC_PER_KM, min(MAX_PACE_SEC_PER_KM, rounded))


def compute_segment_paces(target_pace_sec_per_km: int) -> SegmentPaces:
    """목표/추천 페이스(P) 기준 3구간(몸풀기 · 리듬 유지 · 85% 이후 초기값) 5초 단위 반올림 페이스 계산"""
    return SegmentPaces(
        warmup_pace_sec_per_km=round_pace_5s(target_pace_sec_per_km * WARMUP_PACE_FACTOR),
        rhythm_pace_sec_per_km=round_pace_5s(target_pace_sec_per_km * RHYTHM_PACE_FACTOR),
        realtime_initial_pace_sec_per_km=round_pace_5s(target_pace_sec_per_km * REALTIME_INITIAL_PACE_FACTOR),
    )


def compute_realtime_required_pace(
    target_distance_m: float,
    target_duration_sec: int,
    current_distance_m: float,
    elapsed_sec: float,
    last_announced_pace_sec_per_km: int | None = None,
) -> RealtimePaceResult:
    """
    85% 이후 실시간 필요 페이스 계산 순수 함수:
    - < 85%: 현재 구간(warmup / rhythm) 목표 페이스 안내
    - 85% ~ 95%: 남은 시간의 5% 단축(최대 60초 제한) 적용한 필요 페이스 계산
    - >= 95%: 마지막 안내값(last_announced_pace_sec_per_km) 고정 유지
    - 필요 페이스가 목표 페이스 대비 10% 이상 빠르거나 240초/km 미만 또는 남은 시간 <= 0이면 completion_first 전환
    """
    if target_distance_m <= 0:
        raise ValueError("target_distance_m must be positive")

    target_pace = target_duration_sec / (target_distance_m / 1000.0)
    segments = compute_segment_paces(round_half_up_int(target_pace))
    progress_ratio = current_distance_m / target_distance_m

    if progress_ratio < 0.85:
        if progress_ratio < 0.15:
            return RealtimePaceResult(
                required_pace_sec_per_km=segments.warmup_pace_sec_per_km,
                guidance_mode="warmup",
                early_arrival_sec=0.0,
                is_frozen=False,
            )
        return RealtimePaceResult(
            required_pace_sec_per_km=segments.rhythm_pace_sec_per_km,
            guidance_mode="rhythm",
            early_arrival_sec=0.0,
            is_frozen=False,
        )

    if progress_ratio >= 0.95:
        frozen = (
            last_announced_pace_sec_per_km
            if last_announced_pace_sec_per_km is not None
            else segments.realtime_initial_pace_sec_per_km
        )
        mode = (
            "completion_first"
            if (frozen <= target_pace * 0.9 or frozen < MIN_PACE_SEC_PER_KM)
            else "realtime_frozen"
        )
        return RealtimePaceResult(
            required_pace_sec_per_km=frozen,
            guidance_mode=mode,
            early_arrival_sec=0.0,
            is_frozen=True,
        )

    remaining_distance_km = (target_distance_m - current_distance_m) / 1000.0
    remaining_sec = target_duration_sec - elapsed_sec

    if remaining_sec <= 0 or remaining_distance_km <= 0:
        return RealtimePaceResult(
            required_pace_sec_per_km=round_pace_5s(target_pace),
            guidance_mode="completion_first",
            early_arrival_sec=0.0,
            is_frozen=False,
        )

    early_arrival_sec = min(60.0, max(0.0, remaining_sec * 0.05))
    raw_required_pace = (remaining_sec - early_arrival_sec) / remaining_distance_km
    required_pace_5s = round_pace_5s(raw_required_pace)

    if raw_required_pace <= target_pace * 0.9 or raw_required_pace < MIN_PACE_SEC_PER_KM:
        return RealtimePaceResult(
            required_pace_sec_per_km=required_pace_5s,
            guidance_mode="completion_first",
            early_arrival_sec=early_arrival_sec,
            is_frozen=False,
        )

    return RealtimePaceResult(
        required_pace_sec_per_km=required_pace_5s,
        guidance_mode="realtime",
        early_arrival_sec=early_arrival_sec,
        is_frozen=False,
    )


def _recency_weight(age_days: float) -> float | None:
    if age_days < 0 or age_days > 28.0:
        return None
    if age_days <= 7.0:
        return 1.0
    if age_days <= 14.0:
        return 0.8
    if age_days <= 21.0:
        return 0.6
    return 0.4


def compute_recommended_goal(
    *,
    now_kst: datetime,
    recent_runs: list[dict],
    baseline_status: MetricStatusType,
    baseline_pace_sec_per_km: int | None,
    running_experience: str | None,
    weekly_runs: str | None,
) -> RecommendedGoalView:
    """
    P!PACE 4단계 추천 목표 산식:
    1. 최근 28일 유효 GPS 러닝 3개 이상 -> 최근 기록 가중 평균(기준 페이스 있으면 60%+40%, 없으면 100%)
    2. 기초 측정 완료 & 유효 기록 3개 미만 -> 기준 페이스 100% (온보딩 미반영)
    3. 기초 측정 전 & 온보딩 응답 보유 -> 온보딩 경험/주간횟수 테이블
    4. 아무 정보도 없는 경우 -> 기본 420초(7:00/km)
    """
    valid_weighted_sum = 0.0
    total_weight = 0.0
    valid_run_count = 0

    for run in recent_runs:
        if run.get("mode") != "gps":
            continue
        dist_m = run.get("distance_m")
        pace = run.get("avg_pace_sec_per_km")
        started_at = run.get("started_at")
        completion = run.get("completion")

        if dist_m is None or float(dist_m) < 1000.0:
            continue
        if pace is None or not (MIN_PACE_SEC_PER_KM <= int(pace) <= MAX_PACE_SEC_PER_KM):
            continue
        if started_at is None:
            continue

        started_kst = started_at.astimezone(KST) if started_at.tzinfo else started_at.replace(tzinfo=KST)
        age_days = (now_kst - started_kst).total_seconds() / 86400.0
        recency_w = _recency_weight(age_days)
        if recency_w is None:
            continue

        completion_w = 1.0 if completion == "goal" else 0.5
        weight = recency_w * completion_w
        valid_weighted_sum += int(pace) * weight
        total_weight += weight
        valid_run_count += 1

    has_valid_baseline = baseline_status == MetricStatusType.valid and baseline_pace_sec_per_km is not None

    if valid_run_count >= 3 and total_weight > 0:
        recent_weighted_pace = valid_weighted_sum / total_weight
        if has_valid_baseline:
            raw_pace = recent_weighted_pace * 0.6 + float(baseline_pace_sec_per_km) * 0.4
            desc = "최근 28일 러닝 기록(60%)과 기초 측정 기준 페이스(40%)를 반영한 추천 목표입니다."
        else:
            raw_pace = recent_weighted_pace
            desc = "최근 28일 러닝 기록을 바탕으로 산출된 맞춤 추천 목표입니다."
        final_pace = clamp_pace(raw_pace)
        basis_type = "recent_runs"
    elif has_valid_baseline:
        final_pace = clamp_pace(float(baseline_pace_sec_per_km))
        basis_type = "baseline"
        desc = "기초 측정 기준 페이스를 바탕으로 설정된 목표입니다."
    elif running_experience in ONBOARDING_PACE_TABLE:
        weekly_key = weekly_runs if weekly_runs in ("1", "2", "3+") else "2"
        final_pace = ONBOARDING_PACE_TABLE[running_experience][weekly_key]
        basis_type = "onboarding"
        desc = "온보딩 러닝 경험과 주간 러닝 횟수를 바탕으로 설정된 첫 추천 목표입니다."
    else:
        final_pace = DEFAULT_STARTER_PACE_SEC_PER_KM
        basis_type = "default_starter"
        desc = "누구나 부담 없이 시작할 수 있는 기본 3.0 km 목표입니다."

    segments = compute_segment_paces(final_pace)
    return RecommendedGoalView(
        distance_km=RECOMMENDED_DISTANCE_KM,
        target_duration_sec=final_pace * 3,
        target_pace_sec_per_km=final_pace,
        basis_type=basis_type,
        basis_description=desc,
        display_pace_sec_per_km=round_pace_5s(final_pace),
        warmup_pace_sec_per_km=segments.warmup_pace_sec_per_km,
        rhythm_pace_sec_per_km=segments.rhythm_pace_sec_per_km,
        realtime_initial_pace_sec_per_km=segments.realtime_initial_pace_sec_per_km,
    )


class RecommendationService:
    @staticmethod
    async def get_recommended_goal(
        db: AsyncSession,
        user_id: UUID,
        now_kst: datetime | None = None,
    ) -> tuple[RecommendedGoalView, MetricStatusType]:
        uid = str(user_id)
        ref_now = now_kst or datetime.now(KST)
        since_kst = ref_now - timedelta(days=28)

        profile_row = (
            await db.execute(
                text("SELECT running_experience, weekly_runs FROM public.user_profiles WHERE user_id = :uid"),
                {"uid": uid},
            )
        ).first()
        running_experience = profile_row._mapping["running_experience"] if profile_row else None
        weekly_runs = profile_row._mapping["weekly_runs"] if profile_row else None

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

        runs_rows = (
            await db.execute(
                text(
                    """
                    SELECT started_at, mode, completion, distance_m, avg_pace_sec_per_km
                    FROM public.run_sessions
                    WHERE user_id = :uid
                      AND started_at >= :since_kst
                      AND started_at <= :now_kst
                    ORDER BY started_at DESC
                    """
                ),
                {"uid": uid, "since_kst": since_kst, "now_kst": ref_now},
            )
        ).fetchall()

        goal = compute_recommended_goal(
            now_kst=ref_now,
            recent_runs=[dict(r._mapping) for r in runs_rows],
            baseline_status=baseline_status,
            baseline_pace_sec_per_km=baseline_pace,
            running_experience=running_experience,
            weekly_runs=weekly_runs,
        )
        return goal, baseline_status
