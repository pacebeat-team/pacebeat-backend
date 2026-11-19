from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class GrowthRepository:
    @staticmethod
    async def fetch_running_sessions_since(db: AsyncSession, uid: str, start_dt: datetime) -> list[dict]:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT mode, completion, distance_m, elapsed_ms, avg_pace_sec_per_km, reflection_difficulty
                    FROM public.run_sessions
                    WHERE user_id = :uid AND started_at >= :start_dt
                    """
                ),
                {"uid": uid, "start_dt": start_dt},
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    @staticmethod
    async def fetch_posture_reports_since(db: AsyncSession, uid: str, start_dt: datetime) -> list[dict]:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT p.posture_status,
                           p.ground_contact_time_left_ms,
                           p.ground_contact_time_right_ms,
                           p.left_load_ratio_pct,
                           p.right_load_ratio_pct,
                           p.feedback_items
                    FROM public.run_posture_reports p
                    JOIN public.run_sessions s ON s.id = p.run_id
                    WHERE p.user_id = :uid AND s.started_at >= :start_dt
                    """
                ),
                {"uid": uid, "start_dt": start_dt},
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]
