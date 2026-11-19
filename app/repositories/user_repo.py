from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class UserRepository:
    @staticmethod
    async def ensure_profile_row(db: AsyncSession, user_id: str) -> dict:
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

    @staticmethod
    async def update_profile(db: AsyncSession, params: dict) -> dict:
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
                params,
            )
        ).first()
        await db.commit()
        return dict(updated._mapping)

    @staticmethod
    async def get_baseline(db: AsyncSession, user_id: str) -> dict | None:
        row = (
            await db.execute(
                text("SELECT * FROM public.user_baselines WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
        ).first()
        return dict(row._mapping) if row else None

    @staticmethod
    async def upsert_baseline(db: AsyncSession, params: dict) -> dict:
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
                params,
            )
        ).first()
        await db.commit()
        return dict(row._mapping)

    @staticmethod
    async def update_guidance(db: AsyncSession, params: dict) -> None:
        await db.execute(
            text(
                """
                UPDATE public.user_profiles
                SET voice_guidance_enabled = :voice_guidance_enabled,
                    vibration_guidance_enabled = :vibration_guidance_enabled,
                    guidance_frequency_km = :guidance_frequency_km,
                    vibration_intensity = :vibration_intensity
                WHERE user_id = :user_id
                """
            ),
            params,
        )
        await db.commit()

    @staticmethod
    async def delete_all_user_data(db: AsyncSession, uid: str) -> None:
        await db.execute(text("DELETE FROM public.run_sessions WHERE user_id = :uid"), {"uid": uid})
        await db.execute(text("DELETE FROM public.insole_devices WHERE user_id = :uid"), {"uid": uid})
        await db.execute(text("DELETE FROM public.user_baselines WHERE user_id = :uid"), {"uid": uid})
        await db.execute(text("DELETE FROM public.user_profiles WHERE user_id = :uid"), {"uid": uid})
        await db.commit()
