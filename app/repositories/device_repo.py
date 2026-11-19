from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DeviceRepository:
    @staticmethod
    async def list_by_user(db: AsyncSession, user_id: str) -> list[dict]:
        rows = await db.execute(
            text("SELECT * FROM public.insole_devices WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return [dict(r._mapping) for r in rows]

    @staticmethod
    async def get_by_side(db: AsyncSession, user_id: str, side: str) -> dict | None:
        row = (
            await db.execute(
                text("SELECT * FROM public.insole_devices WHERE user_id = :user_id AND side = :side"),
                {"user_id": user_id, "side": side},
            )
        ).first()
        return dict(row._mapping) if row else None

    @staticmethod
    async def upsert_device(
        db: AsyncSession,
        user_id: str,
        side: str,
        device_identifier: str,
        firmware_version: str | None,
    ) -> dict:
        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO public.insole_devices (
                        user_id, side, device_identifier, firmware_version, is_connected, last_seen_at
                    ) VALUES (
                        :user_id, :side, :device_identifier, :firmware_version, TRUE, :now
                    )
                    ON CONFLICT (user_id, side) DO UPDATE SET
                        device_identifier = EXCLUDED.device_identifier,
                        firmware_version = EXCLUDED.firmware_version,
                        is_connected = TRUE,
                        last_seen_at = EXCLUDED.last_seen_at
                    RETURNING *
                    """
                ),
                {
                    "user_id": user_id,
                    "side": side,
                    "device_identifier": device_identifier,
                    "firmware_version": firmware_version,
                    "now": datetime.now(timezone.utc),
                },
            )
        ).first()
        await db.commit()
        return dict(row._mapping)

    @staticmethod
    async def update_status(db: AsyncSession, params: dict) -> dict:
        updated = (
            await db.execute(
                text(
                    """
                    UPDATE public.insole_devices
                    SET is_connected = :is_connected,
                        battery_pct = :battery_pct,
                        firmware_version = :firmware_version,
                        calibration_status = :calibration_status,
                        signal_quality = :signal_quality,
                        last_seen_at = :last_seen_at
                    WHERE user_id = :user_id AND side = :side
                    RETURNING *
                    """
                ),
                params,
            )
        ).first()
        await db.commit()
        return dict(updated._mapping)

    @staticmethod
    async def delete_by_side(db: AsyncSession, user_id: str, side: str) -> None:
        await db.execute(
            text("DELETE FROM public.insole_devices WHERE user_id = :user_id AND side = :side"),
            {"user_id": user_id, "side": side},
        )
        await db.commit()
