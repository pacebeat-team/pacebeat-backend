from datetime import datetime
from typing import List, Literal
from uuid import UUID
from pydantic import BaseModel, Field, model_validator
from app.schemas.common import GenderType, MetricStatusType, RunningExperienceType, WeeklyRunsType
from app.schemas.device import InsoleDeviceResponse
from app.schemas.run import RunDetailResponse


class ConsentPayload(BaseModel):
    age_over_14: bool
    terms_of_service: bool
    privacy_policy: bool
    location_terms: bool
    marketing: bool = False
    policy_version: str | None = None
    consented_at: datetime | None = None


class GuidanceSettingsPayload(BaseModel):
    voice_guidance_enabled: bool = True
    vibration_guidance_enabled: bool = True
    guidance_frequency_km: float = Field(default=1.0, ge=0.5, le=10.0)
    vibration_intensity: Literal["low", "medium", "high"] = "medium"
    # 프론트엔드 src/features/my/guidanceSettings.ts 대응 필드
    beat_guidance_enabled: bool = True
    guidance_frequency_mode: Literal["perKm", "offPace", "both"] = "offPace"
    auto_pause_enabled: bool = True


class GuidanceSettingsUpdateRequest(BaseModel):
    """PATCH /api/v1/users/me/guidance 부분 갱신(exclude_unset=True) 요청 스키마"""
    voice_guidance_enabled: bool | None = None
    vibration_guidance_enabled: bool | None = None
    guidance_frequency_km: float | None = Field(default=None, ge=0.5, le=10.0)
    vibration_intensity: Literal["low", "medium", "high"] | None = None
    beat_guidance_enabled: bool | None = None
    guidance_frequency_mode: Literal["perKm", "offPace", "both"] | None = None
    auto_pause_enabled: bool | None = None


class UserProfileUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, min_length=2, max_length=10)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    gender: GenderType | None = None
    height_cm: float | None = Field(default=None, ge=100, le=250)
    weight_kg: float | None = Field(default=None, ge=20, le=250)
    running_experience: RunningExperienceType | None = None
    weekly_runs: WeeklyRunsType | None = None
    consent: ConsentPayload | None = None
    onboarding_completed_at: datetime | None = None
    profile_completed_at: datetime | None = None


class UserProfileResponse(BaseModel):
    user_id: UUID
    nickname: str | None
    birth_year: int | None
    gender: GenderType | None
    height_cm: float | None
    weight_kg: float | None
    running_experience: RunningExperienceType | None
    weekly_runs: WeeklyRunsType | None = None
    consent: ConsentPayload
    guidance: GuidanceSettingsPayload
    onboarding_completed_at: datetime | None
    profile_completed_at: datetime | None


class BaselineUpsertRequest(BaseModel):
    skipped: bool = False
    quality_status: MetricStatusType = MetricStatusType.no_data
    baseline_pace_sec_per_km: int | None = Field(default=None, gt=0)
    cadence_spm: int | None = Field(default=None, gt=0)
    stride_length_cm: float | None = Field(default=None, gt=0)
    valid_duration_ms: int | None = Field(default=None, ge=0)
    distance_m: float | None = Field(default=None, ge=0)
    measured_at: datetime | None = None

    @model_validator(mode="after")
    def enforce_null_when_insufficient(self) -> "BaselineUpsertRequest":
        # 120초(120,000ms) 미만이거나 건너뛰기/데이터 부족이면 기준 페이스를 0이나 추정치로 두지 않고 null로 강제
        if self.skipped or self.quality_status != MetricStatusType.valid:
            self.baseline_pace_sec_per_km = None
        if self.valid_duration_ms is not None and self.valid_duration_ms < 120_000:
            self.quality_status = MetricStatusType.insufficient_data
            self.baseline_pace_sec_per_km = None
        return self


class BaselineResponse(BaseModel):
    user_id: UUID
    skipped: bool
    quality_status: MetricStatusType
    baseline_pace_sec_per_km: int | None
    cadence_spm: int | None
    stride_length_cm: float | None
    valid_duration_ms: int | None
    distance_m: float | None
    measured_at: datetime | None


class FrontendExportRow(BaseModel):
    """프론트엔드 src/features/my/dataExport.ts ExportRow 1:1 호환 스키마"""
    recordId: str
    date: str
    mode: Literal["gps", "time"]
    distanceKm: float | None
    durationSec: int
    paceSecPerKm: int | None


class DataExportResponse(BaseModel):
    exported_at: datetime
    records: List[FrontendExportRow]
    profile: UserProfileResponse
    baseline: BaselineResponse
    insole_devices: List[InsoleDeviceResponse]
    run_sessions: List[RunDetailResponse]  # 구간 기록(splits)과 회고(reflection)가 모두 포함된 상세 목록
