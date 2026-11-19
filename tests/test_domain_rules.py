from datetime import datetime, timezone
from app.schemas.common import MetricStatusType, RunCompletionType, RunModeType
from app.schemas.run import PostureReportPayload, RunCreateRequest, TargetValidateRequest
from app.schemas.user import BaselineUpsertRequest
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
