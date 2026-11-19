from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class RunRepository:
    @staticmethod
    async def list_active_music_presets(db: AsyncSession) -> list[dict]:
        result = await db.execute(
            text(
                """
                SELECT track_id, title, subtitle, bpm, recommended_pace_sec_per_km
                FROM public.music_presets
                WHERE is_active = TRUE
                ORDER BY sort_order ASC
                """
            )
        )
        return [dict(row._mapping) for row in result]

    @staticmethod
    async def list_runs_by_period(
        db: AsyncSession,
        user_id: str,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> list[dict]:
        rows = await db.execute(
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
                ORDER BY s.started_at DESC
                """
            ),
            {"user_id": user_id, "from_dt": from_dt, "to_dt": to_dt},
        )
        return [dict(r._mapping) for r in rows]
