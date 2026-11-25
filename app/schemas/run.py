from datetime import datetime
from typing import List
from uuid import UUID
from pydantic import BaseModel, Field, model_validator
from app.schemas.common import (
    CamelModel,
    MetricStatusType,
    ReflectionDifficultyType,
    ReflectionReasonType,
    RunCompletionType,
    RunModeType,
)


class TargetValidateRequest(BaseModel):
    target_distance_km: float = Field(..., gt=0, le=42.2)
    target_duration_sec: int = Field(..., gt=0)


class TargetValidateResponse(BaseModel):
    target_distance_km: float
    target_duration_sec: int
    target_pace_sec_per_km: int
    is_realistic: bool
    warning_code: str | None  # None | "PACE_TOO_FAST" | "PACE_TOO_SLOW"
    warning_message: str | None


class MusicPresetResponse(CamelModel):
    # 프론트엔드 MusicTrack { id, title, bpm }과 1:1 호환되도록 id 프로퍼티 제공
    track_id: str = Field(..., serialization_alias="id", validation_alias="id")
    title: str
    subtitle: str | None = None
    bpm: int
    recommended_pace_sec_per_km: int | None = None


class RunSplitPayload(BaseModel):
    index: int = Field(..., ge=1)
    distance_m: float = Field(..., gt=0)
    duration_ms: int = Field(..., gt=0)
    pace_sec_per_km: int | None = Field(default=None, gt=0)


class GpsGapPayload(BaseModel):
    lost_at_ms: int = Field(..., ge=0)
    recovered_at_ms: int | None = Field(default=None, ge=0)


class RunReflectionPayload(BaseModel):
    difficulty: ReflectionDifficultyType | None = None
    reasons: List[ReflectionReasonType] = Field(default_factory=list)
    memo: str = Field(default="", max_length=100)


class PressureDistributionPayload(BaseModel):
    forefoot_pct: float = Field(..., ge=0, le=100)
    midfoot_pct: float = Field(..., ge=0, le=100)
    heel_pct: float = Field(..., ge=0, le=100)


class PostureReportPayload(BaseModel):
    posture_status: MetricStatusType
    left_connected: bool
    right_connected: bool
    ground_contact_time_left_ms: int | None = Field(default=None, gt=0)
    ground_contact_time_right_ms: int | None = Field(default=None, gt=0)
    left_load_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    right_load_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    left_pressure_distribution: PressureDistributionPayload | None = None
    right_pressure_distribution: PressureDistributionPayload | None = None
    left_landing_pattern: str | None = None
    right_landing_pattern: str | None = None
    feedback_items: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_single_foot_and_missing(self) -> "PostureReportPayload":
        # 한쪽 인솔만 연결된 경우 single_foot 상태로 강제하고 양발 하중 비교 지표를 숨김(null)
        if self.left_connected != self.right_connected:
            self.posture_status = MetricStatusType.single_foot
        if self.posture_status == MetricStatusType.single_foot:
            self.left_load_ratio_pct = None
            self.right_load_ratio_pct = None
            if not self.left_connected:
                self.ground_contact_time_left_ms = None
                self.left_pressure_distribution = None
                self.left_landing_pattern = None
            if not self.right_connected:
                self.ground_contact_time_right_ms = None
                self.right_pressure_distribution = None
                self.right_landing_pattern = None
        return self


class RunCreateRequest(BaseModel):
    client_session_id: str = Field(..., min_length=1, max_length=128)
    mode: RunModeType
    completion: RunCompletionType
    started_at: datetime
    ended_at: datetime
    elapsed_ms: int = Field(..., gt=0)

    target_distance_km: float | None = Field(default=None, gt=0)
    target_duration_sec: int | None = Field(default=None, gt=0)

    distance_m: float | None = Field(default=None, ge=0)
    avg_pace_sec_per_km: int | None = Field(default=None, gt=0)
    cadence_spm: int | None = Field(default=None, gt=0)
    step_count: int | None = Field(default=None, ge=0)
    target_pace_keep_ratio_pct: float | None = Field(default=None, ge=0, le=100)

    pace_status: MetricStatusType = MetricStatusType.valid
    cadence_status: MetricStatusType = MetricStatusType.no_data
    music_track_id: str | None = None

    splits: List[RunSplitPayload] = Field(default_factory=list)
    gps_gaps: List[GpsGapPayload] = Field(default_factory=list)
    reflection: RunReflectionPayload | None = None
    # 스마트 인솔이 연결되어 유효한 데이터를 얻은 세션에만 전달 (미연결 시 None)
    posture_report: PostureReportPayload | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_frontend_nested_run_record(cls, data: dict) -> dict:
        """
        프론트엔드 src/features/running/types.ts 의 RunRecord 객체
        ({ recordId, sessionId, mode, startedAt, endedAt, goal, musicTrackId, result, reflection, sensorReport })를
        그대로 POST /api/v1/runs 바디에 넘겨도 자동 매핑되도록 지원.
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)
        # recordId 또는 sessionId를 client_session_id로 매핑
        if "client_session_id" not in out and "clientSessionId" not in out:
            out["client_session_id"] = out.get("recordId") or out.get("sessionId")
        if "started_at" not in out and "startedAt" in out:
            out["started_at"] = out.get("startedAt")
        if "ended_at" not in out and "endedAt" in out:
            out["ended_at"] = out.get("endedAt")
        if "music_track_id" not in out and "musicTrackId" in out:
            out["music_track_id"] = out.get("musicTrackId")
        # 중첩된 goal: { targetDistanceKm, targetDurationSec } 펼치기
        goal = out.get("goal")
        if isinstance(goal, dict):
            out.setdefault("target_distance_km", goal.get("targetDistanceKm") or goal.get("target_distance_km"))
            out.setdefault("target_duration_sec", goal.get("targetDurationSec") or goal.get("target_duration_sec"))
        # 중첩된 result: { elapsedMs, distanceM, avgPaceSecPerKm, splits, completion, gpsGaps } 펼치기
        result = out.get("result")
        if isinstance(result, dict):
            out.setdefault("elapsed_ms", result.get("elapsedMs") or result.get("elapsed_ms"))
            out.setdefault("distance_m", result.get("distanceM") if "distanceM" in result else result.get("distance_m"))
            out.setdefault(
                "avg_pace_sec_per_km",
                result.get("avgPaceSecPerKm") if "avgPaceSecPerKm" in result else result.get("avg_pace_sec_per_km"),
            )
            out.setdefault("completion", result.get("completion"))
            if "splits" in result and "splits" not in out:
                out["splits"] = result["splits"]
            if "gpsGaps" in result and "gps_gaps" not in out:
                out["gps_gaps"] = result["gpsGaps"]
        # sensorReport가 null로 오면 posture_report = None과 동일 취급
        if "sensorReport" in out and "posture_report" not in out:
            out["posture_report"] = out.get("sensorReport")
        return out

    @model_validator(mode="after")
    def enforce_time_mode_and_null_rules(self) -> "RunCreateRequest":
        if self.mode == RunModeType.time:
            self.completion = RunCompletionType.time
            self.distance_m = None
            self.avg_pace_sec_per_km = None
            self.target_distance_km = None
            self.target_duration_sec = None
            self.splits = []
            self.pace_status = MetricStatusType.no_data
        elif self.distance_m is None or self.distance_m <= 0:
            self.avg_pace_sec_per_km = None
            if self.pace_status == MetricStatusType.valid:
                self.pace_status = MetricStatusType.insufficient_data
        return self


class RunSummaryItemResponse(BaseModel):
    run_id: UUID
    client_session_id: str
    mode: RunModeType
    completion: RunCompletionType
    started_at: datetime
    ended_at: datetime
    elapsed_ms: int
    distance_m: float | None
    avg_pace_sec_per_km: int | None
    pace_status: MetricStatusType
    has_posture_report: bool


class RunDetailResponse(RunSummaryItemResponse):
    target_distance_km: float | None
    target_duration_sec: int | None
    target_pace_sec_per_km: int | None
    cadence_spm: int | None
    cadence_status: MetricStatusType
    step_count: int | None
    target_pace_keep_ratio_pct: float | None
    music_track_id: str | None
    splits: List[RunSplitPayload]
    gps_gaps: List[GpsGapPayload]
    reflection: RunReflectionPayload | None
    posture_report: PostureReportPayload | None


class RunBulkDeleteResponse(BaseModel):
    deleted_count: int
