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


@router.get("/baseline", response_model=BaselineResponse)
async def get_my_baseline(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> BaselineResponse:
    row = (
        await db.execute(
            text("SELECT * FROM public.user_baselines WHERE user_id = :user_id"),
            {"user_id": str(user.user_id)},
        )
    ).first()
    if not row:
        return BaselineResponse(
            user_id=user.user_id,
            skipped=False,
            quality_status=MetricStatusType.no_data,
            baseline_pace_sec_per_km=None,
            cadence_spm=None,
            stride_length_cm=None,
            valid_duration_ms=None,
            distance_m=None,
            measured_at=None,
        )
    m = row._mapping
    return BaselineResponse(
        user_id=m["user_id"],
        skipped=m["skipped"],
        quality_status=m["quality_status"],
        baseline_pace_sec_per_km=m["baseline_pace_sec_per_km"],
        cadence_spm=m["cadence_spm"],
        stride_length_cm=float(m["stride_length_cm"]) if m["stride_length_cm"] is not None else None,
        valid_duration_ms=m["valid_duration_ms"],
        distance_m=float(m["distance_m"]) if m["distance_m"] is not None else None,
        measured_at=m["measured_at"],
    )


@router.put("/baseline", response_model=BaselineResponse)
async def upsert_my_baseline(
    payload: BaselineUpsertRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> BaselineResponse:
    row = (
        await db.execute(
            text(
                """
                INSERT INTO public.user_baselines (
                    user_id, skipped, quality_status, baseline_pace_sec_per_km,
                    cadence_spm, stride_length_cm, valid_duration_ms, distance_m, measured_at
                ) VALUES (
                    :user_id, :skipped, :quality_status, :baseline_pace_sec_per_km,
                    :cadence_spm, :stride_length_cm, :valid_duration_ms, :distance_m, :measured_at
                )
                ON CONFLICT (user_id) DO UPDATE SET
                    skipped = EXCLUDED.skipped,
                    quality_status = EXCLUDED.quality_status,
                    baseline_pace_sec_per_km = EXCLUDED.baseline_pace_sec_per_km,
                    cadence_spm = EXCLUDED.cadence_spm,
                    stride_length_cm = EXCLUDED.stride_length_cm,
                    valid_duration_ms = EXCLUDED.valid_duration_ms,
                    distance_m = EXCLUDED.distance_m,
                    measured_at = EXCLUDED.measured_at
                RETURNING *
                """
            ),
            {
                "user_id": str(user.user_id),
                "skipped": payload.skipped,
                "quality_status": payload.quality_status.value,
                "baseline_pace_sec_per_km": payload.baseline_pace_sec_per_km,
                "cadence_spm": payload.cadence_spm,
                "stride_length_cm": payload.stride_length_cm,
                "valid_duration_ms": payload.valid_duration_ms,
                "distance_m": payload.distance_m,
                "measured_at": payload.measured_at or datetime.now(timezone.utc),
            },
        )
    ).first()
    await db.commit()
    m = row._mapping
    return BaselineResponse(
        user_id=m["user_id"],
        skipped=m["skipped"],
        quality_status=m["quality_status"],
        baseline_pace_sec_per_km=m["baseline_pace_sec_per_km"],
        cadence_spm=m["cadence_spm"],
        stride_length_cm=float(m["stride_length_cm"]) if m["stride_length_cm"] is not None else None,
        valid_duration_ms=m["valid_duration_ms"],
        distance_m=float(m["distance_m"]) if m["distance_m"] is not None else None,
        measured_at=m["measured_at"],
    )


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
