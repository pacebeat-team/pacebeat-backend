from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.user_repo import UserRepository
from app.schemas.common import MetricStatusType
from app.schemas.user import (
    BaselineResponse,
    BaselineUpsertRequest,
    ConsentPayload,
    GuidanceSettingsPayload,
    UserProfileResponse,
    UserProfileUpdateRequest,
)


def to_profile_response(m: dict) -> UserProfileResponse:
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
        ),
        onboarding_completed_at=m["onboarding_completed_at"],
        profile_completed_at=m["profile_completed_at"],
    )


class UserService:
    @staticmethod
    async def get_profile(db: AsyncSession, user_id: UUID) -> UserProfileResponse:
        m = await UserRepository.ensure_profile_row(db, str(user_id))
        return to_profile_response(m)

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        user_id: UUID,
        payload: UserProfileUpdateRequest,
    ) -> UserProfileResponse:
        uid = str(user_id)
        current = await UserRepository.ensure_profile_row(db, uid)
        fields = payload.model_dump(exclude_unset=True)

        consent = fields.pop("consent", None)
        if consent:
            current["consent_age_over_14"] = consent["age_over_14"]
            current["consent_terms_of_service"] = consent["terms_of_service"]
            current["consent_privacy_policy"] = consent["privacy_policy"]
            current["consent_location_terms"] = consent["location_terms"]
            current["consent_marketing"] = consent["marketing"]
            current["consent_policy_version"] = consent["policy_version"]
            current["consented_at"] = consent["consented_at"] or datetime.now(timezone.utc)

        for k, v in fields.items():
            current[k] = v.value if hasattr(v, "value") else v

        updated = await UserRepository.update_profile(db, current)
        return to_profile_response(updated)

    @staticmethod
    async def get_baseline(db: AsyncSession, user_id: UUID) -> BaselineResponse:
        m = await UserRepository.get_baseline(db, str(user_id))
        if not m:
            return BaselineResponse(
                user_id=user_id,
                skipped=False,
                quality_status=MetricStatusType.no_data,
                baseline_pace_sec_per_km=None,
                cadence_spm=None,
                stride_length_cm=None,
                valid_duration_ms=None,
                distance_m=None,
                measured_at=None,
            )
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

    @staticmethod
    async def upsert_baseline(
        db: AsyncSession,
        user_id: UUID,
        payload: BaselineUpsertRequest,
    ) -> BaselineResponse:
        m = await UserRepository.upsert_baseline(
            db,
            {
                "user_id": str(user_id),
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

    @staticmethod
    async def update_guidance(
        db: AsyncSession,
        user_id: UUID,
        payload: GuidanceSettingsPayload,
    ) -> GuidanceSettingsPayload:
        uid = str(user_id)
        await UserRepository.ensure_profile_row(db, uid)
        await UserRepository.update_guidance(db, {"user_id": uid, **payload.model_dump()})
        return payload

    @staticmethod
    async def export_user_data(db: AsyncSession, user_id: UUID) -> dict:
        uid = str(user_id)
        profile = await UserService.get_profile(db, user_id)
        baseline = await UserService.get_baseline(db, user_id)
        runs_rows = await db.execute(
            text("SELECT * FROM public.run_sessions WHERE user_id = :uid ORDER BY started_at DESC"),
            {"uid": uid},
        )
        posture_rows = await db.execute(
            text("SELECT * FROM public.run_posture_reports WHERE user_id = :uid"),
            {"uid": uid},
        )
        device_rows = await db.execute(
            text("SELECT * FROM public.insole_devices WHERE user_id = :uid"),
            {"uid": uid},
        )
        return {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile.model_dump(mode="json"),
            "baseline": baseline.model_dump(mode="json"),
            "insole_devices": [dict(r._mapping) for r in device_rows],
            "run_sessions": [dict(r._mapping) for r in runs_rows],
            "posture_reports": [dict(r._mapping) for r in posture_rows],
        }

    @staticmethod
    async def delete_account_data(db: AsyncSession, user_id: UUID) -> None:
        await UserRepository.delete_all_user_data(db, str(user_id))
