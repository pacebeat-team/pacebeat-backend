from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from app.main import app
from app.routers.growth import _build_calendar_ranges
from app.schemas.common import GrowthPeriodType, MetricStatusType, RunCompletionType, RunModeType
from app.schemas.run import PostureReportPayload, RunCreateRequest, TargetValidateRequest
from app.schemas.user import BaselineUpsertRequest, FrontendExportRow, GuidanceSettingsUpdateRequest
from app.services.recommendation_service import (
    compute_realtime_required_pace,
    compute_recommended_goal,
)
from app.services.run_service import RunService


def test_baseline_enforces_null_when_under_120_seconds() -> None:
    req = BaselineUpsertRequest(
        skipped=False,
        quality_status=MetricStatusType.valid,
        baseline_pace_sec_per_km=360,
        valid_duration_ms=95_000,
    )
    assert req.quality_status == MetricStatusType.insufficient_data
    assert req.baseline_pace_sec_per_km is None


def test_baseline_enforces_null_when_skipped() -> None:
    req = BaselineUpsertRequest(
        skipped=True,
        quality_status=MetricStatusType.valid,
        baseline_pace_sec_per_km=360,
        valid_duration_ms=180_000,
    )
    assert req.baseline_pace_sec_per_km is None


def test_target_pace_validation_boundaries() -> None:
    # 정상 목표: 3km, 18분(1080초) -> 360 sec/km (6'00"/km)
    valid_res = RunService.validate_target(TargetValidateRequest(target_distance_km=3.0, target_duration_sec=1080))
    assert valid_res.is_realistic is True
    assert valid_res.target_pace_sec_per_km == 360
    assert valid_res.warning_code is None

    # 너무 빠른 목표: 3km, 10분(600초) -> 200 sec/km (< 240)
    fast_res = RunService.validate_target(TargetValidateRequest(target_distance_km=3.0, target_duration_sec=600))
    assert fast_res.is_realistic is False
    assert fast_res.warning_code == "PACE_TOO_FAST"

    # 너무 느린 목표: 3km, 35분(2100초) -> 700 sec/km (> 600)
    slow_res = RunService.validate_target(TargetValidateRequest(target_distance_km=3.0, target_duration_sec=2100))
    assert slow_res.is_realistic is False
    assert slow_res.warning_code == "PACE_TOO_SLOW"


def test_time_mode_enforces_null_distance_and_pace() -> None:
    now = datetime.now(timezone.utc)
    req = RunCreateRequest(
        client_session_id="session-time-001",
        mode=RunModeType.time,
        completion=RunCompletionType.goal,
        started_at=now,
        ended_at=now,
        elapsed_ms=1200_000,
        distance_m=3000.0,
        avg_pace_sec_per_km=400,
        target_distance_km=3.0,
        target_duration_sec=1200,
    )
    assert req.completion == RunCompletionType.time
    assert req.distance_m is None
    assert req.avg_pace_sec_per_km is None
    assert req.target_distance_km is None
    assert req.target_duration_sec is None
    assert req.pace_status == MetricStatusType.no_data


def test_single_foot_posture_report_clears_bilateral_load_ratios() -> None:
    report = PostureReportPayload(
        posture_status=MetricStatusType.valid,
        left_connected=True,
        right_connected=False,
        ground_contact_time_left_ms=245,
        ground_contact_time_right_ms=250,
        left_load_ratio_pct=50.0,
        right_load_ratio_pct=50.0,
    )
    assert report.posture_status == MetricStatusType.single_foot
    assert report.left_load_ratio_pct is None
    assert report.right_load_ratio_pct is None
    assert report.ground_contact_time_left_ms == 245
    assert report.ground_contact_time_right_ms is None


def test_guidance_partial_update_preserves_unset_fields() -> None:
    req = GuidanceSettingsUpdateRequest(beat_guidance_enabled=False)
    patch = req.model_dump(exclude_unset=True)
    assert patch == {"beat_guidance_enabled": False}


def test_kst_calendar_ranges_weekly_and_monthly() -> None:
    kst = ZoneInfo("Asia/Seoul")
    now_kst = datetime(2026, 11, 25, 10, 0, tzinfo=kst)  # 수요일
    weekly = _build_calendar_ranges(now_kst, GrowthPeriodType.weekly)
    assert len(weekly) == 2
    assert weekly[0][0].isoformat() == "2026-11-16"
    assert weekly[1][0].isoformat() == "2026-11-23"

    monthly = _build_calendar_ranges(now_kst, GrowthPeriodType.monthly)
    assert len(monthly) >= 4
    assert monthly[0][0].isoformat() == "2026-11-01"


def test_frontend_export_row_accepts_null_pace() -> None:
    row = FrontendExportRow(
        recordId="rec-time-1",
        date="2026-11-25T01:00:00+00:00",
        mode="time",
        distanceKm=None,
        durationSec=600,
        paceSecPerKm=None,
    )
    assert row.paceSecPerKm is None


def test_fastapi_routes_registered() -> None:
    paths = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes}
    assert ("/api/v1/runs/{run_id}", ("DELETE",)) in paths
    assert ("/api/v1/runs/by-session/{client_session_id}", ("DELETE",)) in paths
    assert any(p == "/api/v1/runs" and "DELETE" in m for p, m in paths)
    assert any(p == "/api/v1/users/me/guidance" and "PATCH" in m for p, m in paths)
    assert any(p == "/api/v1/users/me/data-export" and "POST" in m for p, m in paths)


@pytest.mark.parametrize(
    "exp,weekly,pace,dur,warmup,rhythm,realtime",
    [
        ("beginner", "1", 480, 1440, 505, 475, 455),
        ("beginner", "2", 465, 1395, 490, 460, 440),
        ("beginner", "3+", 450, 1350, 475, 445, 430),
        ("occasional", "1", 435, 1305, 455, 430, 415),
        ("occasional", "2", 420, 1260, 440, 415, 400),
        ("occasional", "3+", 405, 1215, 425, 400, 385),
        ("regular", "1", 405, 1215, 425, 400, 385),
        ("regular", "2", 390, 1170, 410, 385, 370),
        ("regular", "3+", 375, 1125, 395, 370, 355),
    ],
)
def test_onboarding_9_combinations_recommended_goal(
    exp: str,
    weekly: str,
    pace: int,
    dur: int,
    warmup: int,
    rhythm: int,
    realtime: int,
) -> None:
    kst = ZoneInfo("Asia/Seoul")
    goal = compute_recommended_goal(
        now_kst=datetime(2026, 11, 25, 14, 0, tzinfo=kst),
        recent_runs=[],
        baseline_status=MetricStatusType.no_data,
        baseline_pace_sec_per_km=None,
        running_experience=exp,
        weekly_runs=weekly,
    )
    assert goal.basis_type == "onboarding"
    assert goal.distance_km == 3.0
    assert goal.target_pace_sec_per_km == pace
    assert goal.target_duration_sec == dur
    assert goal.warmup_pace_sec_per_km == warmup
    assert goal.rhythm_pace_sec_per_km == rhythm
    assert goal.realtime_initial_pace_sec_per_km == realtime


def test_baseline_overrides_onboarding_without_blending() -> None:
    kst = ZoneInfo("Asia/Seoul")
    goal = compute_recommended_goal(
        now_kst=datetime(2026, 11, 25, 14, 0, tzinfo=kst),
        recent_runs=[],
        baseline_status=MetricStatusType.valid,
        baseline_pace_sec_per_km=350,
        running_experience="beginner",
        weekly_runs="1",
    )
    assert goal.basis_type == "baseline"
    assert goal.target_pace_sec_per_km == 350
    assert goal.target_duration_sec == 1050


def test_recent_runs_filtering_and_weighted_blend_with_baseline() -> None:
    kst = ZoneInfo("Asia/Seoul")
    now_kst = datetime(2026, 11, 25, 14, 0, tzinfo=kst)
    runs = [
        # 유효 1: 3일 전(1.0) * 완주(1.0) = 1.0, pace=400
        {"mode": "gps", "completion": "goal", "distance_m": 3000, "avg_pace_sec_per_km": 400, "started_at": now_kst - timedelta(days=3)},
        # 유효 2: 10일 전(0.8) * 일부(0.5) = 0.4, pace=440
        {"mode": "gps", "completion": "partial", "distance_m": 1500, "avg_pace_sec_per_km": 440, "started_at": now_kst - timedelta(days=10)},
        # 유효 3: 18일 전(0.6) * 완주(1.0) = 0.6, pace=420
        {"mode": "gps", "completion": "goal", "distance_m": 2000, "avg_pace_sec_per_km": 420, "started_at": now_kst - timedelta(days=18)},
        # 제외 1: 1km 미만
        {"mode": "gps", "completion": "goal", "distance_m": 999, "avg_pace_sec_per_km": 300, "started_at": now_kst - timedelta(days=1)},
        # 제외 2: 4:00/km 미만
        {"mode": "gps", "completion": "goal", "distance_m": 3000, "avg_pace_sec_per_km": 239, "started_at": now_kst - timedelta(days=1)},
        # 제외 3: 10:00/km 초과
        {"mode": "gps", "completion": "goal", "distance_m": 3000, "avg_pace_sec_per_km": 601, "started_at": now_kst - timedelta(days=1)},
        # 제외 4: TIME 모드
        {"mode": "time", "completion": "time", "distance_m": None, "avg_pace_sec_per_km": None, "started_at": now_kst - timedelta(days=1)},
        # 제외 5: 28일 초과
        {"mode": "gps", "completion": "goal", "distance_m": 3000, "avg_pace_sec_per_km": 300, "started_at": now_kst - timedelta(days=29)},
    ]
    # recent_weighted = (400*1.0 + 440*0.4 + 420*0.6) / (1.0 + 0.4 + 0.6) = 828 / 2.0 = 414.0
    # blended = 414.0 * 0.6 + 380 * 0.4 = 248.4 + 152.0 = 400.4 -> 400
    goal = compute_recommended_goal(
        now_kst=now_kst,
        recent_runs=runs,
        baseline_status=MetricStatusType.valid,
        baseline_pace_sec_per_km=380,
        running_experience="beginner",
        weekly_runs="1",
    )
    assert goal.basis_type == "recent_runs"
    assert goal.target_pace_sec_per_km == 400
    assert goal.target_duration_sec == 1200


def test_realtime_required_pace_at_85_95_and_completion_first() -> None:
    # 3km, 21분(1260초, 420초/km) 기준 85%(2550m) 지점, 경과시간 1071초(17분51초)
    # 남은 시간 = 189초, 조기 도착 = 189 * 0.05 = 9.45초, 남은 거리 = 0.45km
    # 필요 페이스 = (189 - 9.45) / 0.45 = 399.0 -> 5초 반올림 400초(6:40/km)
    res_85 = compute_realtime_required_pace(
        target_distance_m=3000,
        target_duration_sec=1260,
        current_distance_m=2550,
        elapsed_sec=1071,
    )
    assert res_85.guidance_mode == "realtime"
    assert res_85.required_pace_sec_per_km == 400
    assert res_85.is_frozen is False

    # 95% 이후(2850m): 마지막 안내값(405초) 그대로 고정
    res_95 = compute_realtime_required_pace(
        target_distance_m=3000,
        target_duration_sec=1260,
        current_distance_m=2850,
        elapsed_sec=1190,
        last_announced_pace_sec_per_km=405,
    )
    assert res_95.is_frozen is True
    assert res_95.required_pace_sec_per_km == 405
    assert res_95.guidance_mode == "realtime_frozen"

    # 목표 페이스(420초) 대비 10% 이상 빠르거나(<= 378초) 240초 미만이면 completion_first 전환
    res_fast = compute_realtime_required_pace(
        target_distance_m=3000,
        target_duration_sec=1260,
        current_distance_m=2550,
        elapsed_sec=1120,  # 남은 140초 -> (140 - 7) / 0.45 = 295.5초 <= 378초
    )
    assert res_fast.guidance_mode == "completion_first"


def test_target_validate_includes_segment_paces_and_triggers() -> None:
    res = RunService.validate_target(TargetValidateRequest(target_distance_km=5.0, target_duration_sec=2100))
    assert res.is_realistic is True
    assert res.target_pace_sec_per_km == 420
    assert res.warmup_pace_sec_per_km == 440
    assert res.rhythm_pace_sec_per_km == 415
    assert res.realtime_initial_pace_sec_per_km == 400
    assert res.realtime_trigger_distance_m == 4250.0
    assert res.realtime_freeze_distance_m == 4750.0
