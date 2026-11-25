# Pacebeat 백엔드 미구현 API 및 프론트엔드 계약 정합성 보완 작업 명세서

> **대상 백엔드 경로**: `C:\python\pacebeat-backend`
> **기준 프론트엔드**: `C:\react\pacebeat-frontend` (`develop` / `netlify-production` 통합 완료 버전)
> **목적**: 프론트엔드의 `docs/api-gap-analysis.md`, `docs/backend-contract-investigation.md`, `src/lib/api/types.ts`, `src/features/serverSync/*`에서 확인된 **미지원 API, 인증 알고리즘 불일치(ES256), 스키마 차이, KST 타임존 집계 차이**를 백엔드(`C:\python\pacebeat-backend`)에 빠짐없이 구현하기 위한 실행용 작업 문서입니다.

---

## 0. 작업 요약 (총 7개 핵심 과업)

| 번호 | 구분 | 엔드포인트 / 파일 | 해결하는 프론트엔드 이슈 (Gap / Question) |
|---|---|---|---|
| **Task 1** | 인증 보완 | `app/core/security.py` | **[G10/Q2/Q16]** Supabase `ES256`(JWKS) + `HS256` 동시 검증 및 401 에러 메시지 내부 예외 노출 제거 |
| **Task 2** | **신규 API** | `DELETE /api/v1/runs/{run_id}`<br>`DELETE /api/v1/runs/by-session/{client_session_id}`<br>`DELETE /api/v1/runs` | **[C9/Q9]** 개별 러닝 기록 삭제(서버 `run_id` 및 로컬 `client_session_id` 양방향 지원) + 마이 > "내 데이터 삭제"(프로필 유지, 러닝 기록 전체 초기화) API 신설 |
| **Task 3** | 스키마·API 보완 | `PATCH /api/v1/users/me/guidance`<br>`GET/PATCH /api/v1/users/me` | **[G3/E2/Q6]** 안내 설정 `exclude_unset=True` 부분 갱신 지원 + 프론트엔드 안내 설정 필드(`beat_guidance_enabled`, `guidance_frequency_mode`, `auto_pause_enabled`) 확장 |
| **Task 4** | 미완성 API 완성 | `POST /api/v1/users/me/data-export` | **[E5/Q11]** OpenAPI 응답 스키마(`DataExportResponse`) 명시, `run_splits`(구간 기록) 누락 해결, 프론트 `ExportRow`(`records`) 포맷 동시 제공 |
| **Task 5** | 계정 삭제 보완 | `DELETE /api/v1/users/me` | **[G9/E6/Q10]** DB 트랜잭션 원자적 삭제 + `SUPABASE_SERVICE_ROLE_KEY` 설정 시 Supabase Auth 사용자(`auth.users`)까지 완전 삭제 지원 |
| **Task 6** | 목록·저장 보완 | `GET /api/v1/runs`<br>`POST /api/v1/runs` | **[C10/G4/Q4/Q12]** 프론트 `parseRunList`(최상위 배열) 호환을 유지하면서 `limit`, `offset`, `updated_since` 필터 및 `X-Total-Count` 헤더 지원 |
| **Task 7** | 집계 기준 고도화 | `GET /api/v1/home/summary`<br>`GET /api/v1/growth/running`<br>`GET /api/v1/growth/posture` | **[G7/G8/D1~D4/Q8]** UTC 대신 **KST(`Asia/Seoul`) 월요일 00:00 달력 기준** 적용, 월간 주차별 시계열 버킷 배열 및 이전 기간 비교 데이터, 거리 가중 평균 페이스 산출 |

---

## 1. Supabase DB 추가 마이그레이션 SQL (`sql/002_frontend_alignment.sql`)

Supabase SQL Editor에서 아래 스크립트를 실행하여 프론트엔드 안내 설정 필드와 조회 인덱스를 추가합니다 (기존 데이터와 100% 하위 호환됩니다).

```sql
-- ============================================================================
-- 002_frontend_alignment.sql
-- 프론트엔드 안내 설정(beatGuide, frequency, autoPause) 및 증분 동기화 인덱스 추가
-- ============================================================================

DO $$ BEGIN
    -- 프론트엔드 src/features/my/guidanceSettings.ts GuidanceFrequency ('perKm' | 'offPace' | 'both')
    CREATE TYPE guidance_frequency_mode_type AS ENUM ('perKm', 'offPace', 'both');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE public.user_profiles
    ADD COLUMN IF NOT EXISTS beat_guidance_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS guidance_frequency_mode guidance_frequency_mode_type NOT NULL DEFAULT 'offPace',
    ADD COLUMN IF NOT EXISTS auto_pause_enabled BOOLEAN NOT NULL DEFAULT TRUE;

-- 증분 동기화(updated_since) 및 client_session_id 조회 최적화 인덱스
CREATE INDEX IF NOT EXISTS idx_run_sessions_user_updated_at
    ON public.run_sessions(user_id, updated_at DESC);
```

---

## 2. [Task 1] Supabase `ES256`(JWKS) + `HS256` 동시 검증 (`app/core/security.py`, `app/core/config.py`)

### 2-1. `app/core/config.py` (`SUPABASE_SERVICE_ROLE_KEY` 선택 환경변수 추가)

```python
import json
from functools import lru_cache
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "pacebeat-backend"
    APP_ENV: str = "development"
    PORT: int = 8000
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "https://pipace.netlify.app"]

    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_JWT_SECRET: str
    # 계정 완전 탈퇴(auth.users 삭제) 시 사용하는 선택적 Service Role 키
    SUPABASE_SERVICE_ROLE_KEY: str | None = None
    DATABASE_URL: str

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### 2-2. `app/core/security.py` (ES256 JWKS 지원 및 보안 에러 메시지 정제)

```python
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID
import jwt
from jwt import PyJWKClient
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import Settings, get_settings
from app.core.errors import AppError

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    email: str | None


@lru_cache
def get_jwk_client(supabase_url: str) -> PyJWKClient:
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return PyJWKClient(jwks_url, cache_keys=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_MISSING_TOKEN",
            message="인증 토큰이 필요합니다.",
        )

    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")

        if alg == "HS256":
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        else:
            signing_key = get_jwk_client(settings.SUPABASE_URL).get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                options={"verify_aud": False},
            )

        sub = payload.get("sub")
        if not sub:
            raise ValueError("Missing sub claim")
        return AuthenticatedUser(user_id=UUID(sub), email=payload.get("email"))
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_TOKEN_EXPIRED",
            message="인증 토큰이 만료되었습니다.",
        ) from exc
    except (jwt.PyJWTError, ValueError) as exc:
        # Q16 반영: 내부 예외 상세나 시크릿 정보를 응답에 노출하지 않음
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_INVALID_TOKEN",
            message="유효하지 않은 인증 토큰입니다.",
        ) from exc
```

---

## 3. [Task 2 & Task 6] 러닝 기록 삭제 API 3종 신설 및 목록 조회 고도화

### 3-1. `app/schemas/run.py` 추가 스키마

`app/schemas/run.py`에 삭제 응답 스키마를 추가합니다.

```python
class RunBulkDeleteResponse(BaseModel):
    deleted_count: int
```

### 3-2. `app/routers/runs.py` (삭제 API 3종 + `limit`/`offset`/`updated_since` 필터)

- **주의**: 프론트엔드 `src/features/serverSync/runMapper.ts`의 `parseRunList(raw)`는 `Array.isArray(raw)`일 때만 파싱합니다. 따라서 `GET /api/v1/runs`의 응답 본문은 반드시 기존처럼 **최상위 배열(`list[RunSummaryItemResponse]`)**을 유지하고, 전체 개수와 다음 페이지 여부는 응답 헤더(`X-Total-Count`, `X-Has-More`)로 내려줍니다.

```python
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import AuthenticatedUser, get_current_user
from app.schemas.run import (
    MusicPresetResponse,
    RunBulkDeleteResponse,
    RunCreateRequest,
    RunDetailResponse,
    RunReflectionPayload,
    RunSummaryItemResponse,
    TargetValidateRequest,
    TargetValidateResponse,
)
from app.services.run_service import RunService

router = APIRouter(prefix="/api/v1", tags=["Running & Records"])


@router.post("/runs/targets/validate", response_model=TargetValidateResponse)
async def validate_run_target(
    payload: TargetValidateRequest,
    _: AuthenticatedUser = Depends(get_current_user),
) -> TargetValidateResponse:
    return RunService.validate_target(payload)


@router.get("/music/presets", response_model=list[MusicPresetResponse])
async def get_music_presets(
    db: AsyncSession = Depends(get_db),
    _: AuthenticatedUser = Depends(get_current_user),
) -> list[MusicPresetResponse]:
    return await RunService.list_music_presets(db)


@router.post("/runs", response_model=RunDetailResponse, status_code=status.HTTP_201_CREATED)
async def save_run_session(
    payload: RunCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> RunDetailResponse:
    return await RunService.upsert_run_session(db, user.user_id, payload)


@router.get("/runs", response_model=list[RunSummaryItemResponse])
async def list_runs(
    response: Response,
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    updated_since: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[RunSummaryItemResponse]:
    params = {
        "user_id": str(user.user_id),
        "from_dt": from_dt,
        "to_dt": to_dt,
        "updated_since": updated_since,
        "limit": limit,
        "offset": offset,
    }
    total_row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM public.run_sessions s
                WHERE s.user_id = :user_id
                  AND (:from_dt IS NULL OR s.started_at >= :from_dt)
                  AND (:to_dt IS NULL OR s.started_at <= :to_dt)
                  AND (:updated_since IS NULL OR s.updated_at >= :updated_since)
                """
            ),
            params,
        )
    ).first()
    total_count = int(total_row._mapping["cnt"]) if total_row else 0

    rows = (
        await db.execute(
            text(
                """
                SELECT s.id AS run_id, s.client_session_id, s.mode, s.completion,
                       s.started_at, s.ended_at, s.elapsed_ms,
                       s.distance_m, s.avg_pace_sec_per_km, s.pace_status,
                       (p.run_id IS NOT NULL) AS has_posture_report
                FROM public.run_sessions s
                LEFT JOIN public.run_posture_reports p ON p.run_id = s.id
                WHERE s.user_id = :user_id
                  AND (:from_dt IS NULL OR s.started_at >= :from_dt)
                  AND (:to_dt IS NULL OR s.started_at <= :to_dt)
                  AND (:updated_since IS NULL OR s.updated_at >= :updated_since)
                ORDER BY s.started_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).fetchall()

    items = [RunSummaryItemResponse(**dict(r._mapping)) for r in rows]
    response.headers["X-Total-Count"] = str(total_count)
    response.headers["X-Has-More"] = "true" if (offset + len(items)) < total_count else "false"
    return items


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run_detail(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> RunDetailResponse:
    return await RunService.get_run_detail(db, user.user_id, run_id)


@router.patch("/runs/{run_id}/reflection", response_model=RunDetailResponse)
async def update_run_reflection(
    run_id: UUID,
    payload: RunReflectionPayload,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> RunDetailResponse:
    res = await db.execute(
        text(
            """
            UPDATE public.run_sessions
            SET reflection_difficulty = :difficulty,
                reflection_reasons = :reasons,
                reflection_memo = :memo
            WHERE id = :run_id AND user_id = :user_id
            RETURNING id
            """
        ),
        {
            "run_id": str(run_id),
            "user_id": str(user.user_id),
            "difficulty": payload.difficulty.value if payload.difficulty else None,
            "reasons": [r.value for r in payload.reasons],
            "memo": payload.memo,
        },
    )
    if not res.first():
        raise AppError(404, "RUN_NOT_FOUND", "해당 러닝 기록을 찾을 수 없습니다.")
    await db.commit()
    return await RunService.get_run_detail(db, user.user_id, run_id)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run_by_id(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Response:
    """개별 러닝 기록 삭제 (서버 UUID run_id 기준, run_splits 및 run_posture_reports는 ON DELETE CASCADE로 함께 삭제)"""
    res = await db.execute(
        text("DELETE FROM public.run_sessions WHERE id = :run_id AND user_id = :user_id RETURNING id"),
        {"run_id": str(run_id), "user_id": str(user.user_id)},
    )
    if not res.first():
        raise AppError(404, "RUN_NOT_FOUND", "해당 러닝 기록을 찾을 수 없습니다.")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/runs/by-session/{client_session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run_by_client_session_id(
    client_session_id: str,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Response:
    """프론트엔드 로컬 sessionId(client_session_id) 기준 개별 러닝 기록 멱등 삭제"""
    await db.execute(
        text(
            """
            DELETE FROM public.run_sessions
            WHERE user_id = :user_id AND client_session_id = :client_session_id
            """
        ),
        {"user_id": str(user.user_id), "client_session_id": client_session_id},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/runs", response_model=RunBulkDeleteResponse)
async def delete_all_my_runs(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> RunBulkDeleteResponse:
    """마이 > 데이터 관리 > '내 데이터 삭제': 프로필·기초 측정은 유지하고 완료된 러닝 기록만 전체 삭제"""
    rows = (
        await db.execute(
            text("DELETE FROM public.run_sessions WHERE user_id = :user_id RETURNING id"),
            {"user_id": str(user.user_id)},
        )
    ).fetchall()
    await db.commit()
    return RunBulkDeleteResponse(deleted_count=len(rows))
```

---

## 4. [Task 3, Task 4, Task 5] 안내 설정 부분 갱신 · 데이터 내보내기 완성 · 계정 삭제 보완

### 4-1. `app/schemas/user.py` (안내 설정 부분 갱신 및 데이터 내보내기 스키마)

- **핵심 변경점**:
  1. `GuidanceSettingsUpdateRequest`: 모든 필드를 `Optional`(`None`)로 두어 `exclude_unset=True`로 **보낸 필드만 부분 갱신**하고, 프론트엔드 `src/features/my/guidanceSettings.ts`의 `beat_guidance_enabled`(`beatGuide`), `guidance_frequency_mode`(`'perKm' | 'offPace' | 'both'`), `auto_pause_enabled`(`autoPause`)까지 모두 수용합니다.
  2. `DataExportResponse`: OpenAPI 스키마에 명시되지 않았던 내보내기 응답을 정식 스키마로 정의하고, **누락되었던 구간 기록(`run_splits`)**과 프론트엔드 `src/features/my/dataExport.ts`의 `ExportRow`(`records`: `recordId, date, mode, distanceKm, durationSec, paceSecPerKm`)를 모두 포함합니다.

```python
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
    paceSecPerKm: int | null


class DataExportResponse(BaseModel):
    exported_at: datetime
    records: List[FrontendExportRow]
    profile: UserProfileResponse
    baseline: BaselineResponse
    insole_devices: List[InsoleDeviceResponse]
    run_sessions: List[RunDetailResponse]  # 구간 기록(splits)과 회고(reflection)가 모두 포함된 상세 목록
```

### 4-2. `app/routers/users.py` (부분 안내 갱신 + `run_splits` 포함 Export + Supabase Auth 계정 삭제)

```python
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import AuthenticatedUser, get_current_user
from app.schemas.common import MetricStatusType
from app.schemas.device import InsoleDeviceResponse
from app.schemas.user import (
    BaselineResponse,
    BaselineUpsertRequest,
    ConsentPayload,
    DataExportResponse,
    FrontendExportRow,
    GuidanceSettingsPayload,
    GuidanceSettingsUpdateRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
)
from app.services.run_service import RunService

router = APIRouter(prefix="/api/v1/users/me", tags=["My - User & Baseline"])


async def _ensure_profile_row(db: AsyncSession, user_id: str) -> dict:
    row = (
        await db.execute(
            text("SELECT * FROM public.user_profiles WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
    ).first()
    if row:
        return dict(row._mapping)

    created = (
        await db.execute(
            text("INSERT INTO public.user_profiles (user_id) VALUES (:user_id) RETURNING *"),
            {"user_id": user_id},
        )
    ).first()
    await db.commit()
    return dict(created._mapping)


def _to_profile_response(m: dict) -> UserProfileResponse:
    return UserProfileResponse(
        user_id=m["user_id"],
        nickname=m["nickname"],
        birth_year=m["birth_year"],
        gender=m["gender"],
        height_cm=float(m["height_cm"]) if m["height_cm"] is not None else None,
        weight_kg=float(m["weight_kg"]) if m["weight_kg"] is not None else None,
        running_experience=m["running_experience"],
        weekly_runs=m.get("weekly_runs"),
        consent=ConsentPayload(
            age_over_14=m["consent_age_over_14"],
            terms_of_service=m["consent_terms_of_service"],
            privacy_policy=m["consent_privacy_policy"],
            location_terms=m["consent_location_terms"],
            marketing=m["consent_marketing"],
            policy_version=m["consent_policy_version"],
            consented_at=m["consented_at"],
        ),
        guidance=GuidanceSettingsPayload(
            voice_guidance_enabled=m["voice_guidance_enabled"],
            vibration_guidance_enabled=m["vibration_guidance_enabled"],
            guidance_frequency_km=float(m["guidance_frequency_km"]),
            vibration_intensity=m["vibration_intensity"],
            beat_guidance_enabled=m.get("beat_guidance_enabled", True),
            guidance_frequency_mode=m.get("guidance_frequency_mode", "offPace"),
            auto_pause_enabled=m.get("auto_pause_enabled", True),
        ),
        onboarding_completed_at=m["onboarding_completed_at"],
        profile_completed_at=m["profile_completed_at"],
    )


@router.get("", response_model=UserProfileResponse)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> UserProfileResponse:
    m = await _ensure_profile_row(db, str(user.user_id))
    return _to_profile_response(m)


@router.patch("", response_model=UserProfileResponse)
async def update_my_profile(
    payload: UserProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> UserProfileResponse:
    uid = str(user.user_id)
    current = await _ensure_profile_row(db, uid)
    fields = payload.model_dump(exclude_unset=True)

    consent = fields.pop("consent", None)
    if consent:
        current["consent_age_over_14"] = consent["age_over_14"]
        current["consent_terms_of_service"] = consent["terms_of_service"]
        current["consent_privacy_policy"] = consent["privacy_policy"]
        current["consent_location_terms"] = consent["location_terms"]
        current["consent_marketing"] = consent.get("marketing", False)
        current["consent_policy_version"] = consent.get("policy_version")
        current["consented_at"] = consent.get("consented_at") or datetime.now(timezone.utc)

    for k, v in fields.items():
        current[k] = v.value if hasattr(v, "value") else v

    updated = (
        await db.execute(
            text(
                """
                UPDATE public.user_profiles
                SET nickname = :nickname,
                    birth_year = :birth_year,
                    gender = :gender,
                    height_cm = :height_cm,
                    weight_kg = :weight_kg,
                    running_experience = :running_experience,
                    weekly_runs = :weekly_runs,
                    consent_age_over_14 = :consent_age_over_14,
                    consent_terms_of_service = :consent_terms_of_service,
                    consent_privacy_policy = :consent_privacy_policy,
                    consent_location_terms = :consent_location_terms,
                    consent_marketing = :consent_marketing,
                    consent_policy_version = :consent_policy_version,
                    consented_at = :consented_at,
                    onboarding_completed_at = :onboarding_completed_at,
                    profile_completed_at = :profile_completed_at
                WHERE user_id = :user_id
                RETURNING *
                """
            ),
            current,
        )
    ).first()
    await db.commit()
    return _to_profile_response(dict(updated._mapping))


@router.patch("/guidance", response_model=GuidanceSettingsPayload)
async def update_my_guidance(
    payload: GuidanceSettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> GuidanceSettingsPayload:
    """
    [G3/Q6 해결] exclude_unset=True 기반 부분 갱신:
    보내지 않은 필드는 기존 DB 값을 그대로 유지하고, 보낸 필드만 업데이트합니다.
    """
    uid = str(user.user_id)
    current = await _ensure_profile_row(db, uid)
    patch = payload.model_dump(exclude_unset=True)
    for k, v in patch.items():
        if v is not None:
            current[k] = v

    updated = (
        await db.execute(
            text(
                """
                UPDATE public.user_profiles
                SET voice_guidance_enabled = :voice_guidance_enabled,
                    vibration_guidance_enabled = :vibration_guidance_enabled,
                    guidance_frequency_km = :guidance_frequency_km,
                    vibration_intensity = :vibration_intensity,
                    beat_guidance_enabled = :beat_guidance_enabled,
                    guidance_frequency_mode = :guidance_frequency_mode,
                    auto_pause_enabled = :auto_pause_enabled
                WHERE user_id = :user_id
                RETURNING *
                """
            ),
            current,
        )
    ).first()
    await db.commit()
    return _to_profile_response(dict(updated._mapping)).guidance


@router.post("/data-export", response_model=DataExportResponse)
async def export_my_data(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> DataExportResponse:
    """
    [E5/Q11 해결] 구간 기록(splits)이 포함된 전체 러닝 상세와
    프론트엔드 dataExport.ts 호환용 records(ExportRow[]) 배열을 함께 반환합니다.
    """
    uid = str(user.user_id)
    profile = await get_my_profile(db=db, user=user)
    baseline = await get_my_baseline(db=db, user=user)

    insole_rows = (
        await db.execute(
            text("SELECT * FROM public.insole_devices WHERE user_id = :uid ORDER BY side ASC"),
            {"uid": uid},
        )
    ).fetchall()
    insoles = [InsoleDeviceResponse(**dict(r._mapping)) for r in insole_rows]

    run_id_rows = (
        await db.execute(
            text("SELECT id FROM public.run_sessions WHERE user_id = :uid ORDER BY started_at DESC"),
            {"uid": uid},
        )
    ).fetchall()

    run_details = [
        await RunService.get_run_detail(db, user.user_id, r._mapping["id"])
        for r in run_id_rows
    ]

    export_rows = [
        FrontendExportRow(
            recordId=f"rec-{r.client_session_id}",
            date=r.started_at.isoformat(),
            mode=r.mode.value,
            distanceKm=round(r.distance_m / 1000.0, 4) if (r.mode.value == "gps" and r.distance_m is not None) else None,
            durationSec=round(r.elapsed_ms / 1000),
            paceSecPerKm=r.avg_pace_sec_per_km if r.mode.value == "gps" else None,
        )
        for r in run_details
    ]

    return DataExportResponse(
        exported_at=datetime.now(timezone.utc),
        records=export_rows,
        profile=profile,
        baseline=baseline,
        insole_devices=insoles,
        run_sessions=run_details,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account_data(
    delete_auth_user: bool = Query(default=True, description="True이고 SUPABASE_SERVICE_ROLE_KEY가 설정된 경우 Supabase Auth 계정까지 삭제"),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    [G9/Q10 해결]
    1. 단일 트랜잭션 안에서 사용자의 모든 앱 데이터(run_sessions, run_splits, run_posture_reports, insole_devices, user_baselines, user_profiles) 삭제
    2. SUPABASE_SERVICE_ROLE_KEY가 설정되어 있고 delete_auth_user=True이면 Supabase Admin API로 auth.users 계정까지 완전 삭제
    """
    uid = str(user.user_id)
    await db.execute(text("DELETE FROM public.run_sessions WHERE user_id = :uid"), {"uid": uid})
    await db.execute(text("DELETE FROM public.insole_devices WHERE user_id = :uid"), {"uid": uid})
    await db.execute(text("DELETE FROM public.user_baselines WHERE user_id = :uid"), {"uid": uid})
    await db.execute(text("DELETE FROM public.user_profiles WHERE user_id = :uid"), {"uid": uid})
    await db.commit()

    if delete_auth_user and settings.SUPABASE_SERVICE_ROLE_KEY:
        admin_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{uid}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.delete(
                admin_url,
                headers={
                    "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
                },
            )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

---

## 5. [Task 7] KST(`Asia/Seoul`) 달력 기준 Home & Growth 시계열 집계 (`app/routers/home.py`, `app/routers/growth.py`)

### 5-1. 왜 수정이 필요한가? (Gap G7 / G8 / Q8)
- 기존 백엔드는 `datetime.now(timezone.utc)`를 기준으로 주간 월요일을 계산하고, Growth에서 최근 7일/30일을 **단일 버킷 1개**로만 묶어 반환하며, 평균 페이스를 단순 산술 평균으로 계산했습니다.
- 프론트엔드(`src/features/home/homeRecords.ts`, `src/features/growth/growthView.ts`)는 다음 규칙을 사용합니다:
  1. **KST(`Asia/Seoul`, UTC+9) 달력 기준 월요일 00:00 시작 주**
  2. **거리 가중 평균 페이스** (`총 GPS 러닝 시간(초) ÷ 총 GPS 거리(km)`, 반올림 정수 `sec/km`)
  3. **TIME 모드 기록은 러닝 횟수·시간에만 포함하고 거리 합계·거리 완주 집계에서는 제외**
  4. **시계열 버킷 배열**:
     - `period=weekly`: 최근 4주(또는 이번 주 + 지난 주) 월요일~일요일 달력 주별 버킷 배열 (막대 차트 및 이전 주 대비 비교 가능)
     - `period=monthly`: 이번 달 1주~5주(월요일 시작 주) 주차별 버킷 배열 (`src/features/growth/growthView.ts`의 `buildMonthlyGrowth`와 동일)

### 5-2. `app/routers/home.py` (KST 월요일 기준 주간 활동 요약)

```python
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
```

### 5-3. `app/routers/growth.py` (KST 달력 주간/월간 시계열 버킷 및 거리 가중 평균 페이스)

```python
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
```

---

## 6. `C:\python\pacebeat-backend`에서 작업 실행 절차

1. 이 문서를 `C:\python\pacebeat-backend\docs\backend-missing-apis-work-spec.md`로 복사(또는 이동)합니다:
   ```powershell
   Move-Item C:\react\pacebeat-frontend\docs\backend-missing-apis-work-spec.md C:\python\pacebeat-backend\backend-missing-apis-work-spec.md
   ```
2. **Supabase SQL Editor**에서 `1. Supabase DB 추가 마이그레이션 SQL` (`002_frontend_alignment.sql`)을 실행합니다.
3. `C:\python\pacebeat-backend` 프로젝트에서 AI 에이전트에게 아래와 같이 지시합니다:
   > `"backend-missing-apis-work-spec.md 문서를 읽고 Task 1부터 Task 7까지의 코드(app/core/config.py, app/core/security.py, app/schemas/run.py, app/schemas/user.py, app/routers/runs.py, app/routers/users.py, app/routers/home.py, app/routers/growth.py)를 현재 백엔드 프로젝트에 그대로 반영하고 테스트해 줘."`
4. 백엔드 커밋 및 푸시 후 Railway 배포가 완료되면 `https://pacebeat-backend-production.up.railway.app/docs`에서 신규/보완된 API(`DELETE /api/v1/runs/{run_id}`, `DELETE /api/v1/runs/by-session/{client_session_id}`, `DELETE /api/v1/runs`, `PATCH /api/v1/users/me/guidance`, `POST /api/v1/users/me/data-export`)가 노출되는지 확인합니다.
