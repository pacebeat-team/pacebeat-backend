from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AppError
from app.repositories.device_repo import DeviceRepository
from app.schemas.common import InsoleSideType
from app.schemas.device import (
    InsoleDeviceResponse,
    InsolePairSummaryResponse,
    InsoleRegisterRequest,
    InsoleStatusUpdateRequest,
)


class DeviceService:
    @staticmethod
    async def get_pair_status(db: AsyncSession, user_id: UUID) -> InsolePairSummaryResponse:
        rows = await DeviceRepository.list_by_user(db, str(user_id))
        by_side: dict[str, InsoleDeviceResponse] = {}
        for m in rows:
            by_side[m["side"]] = InsoleDeviceResponse(**m)

        left = by_side.get("left")
        right = by_side.get("right")
        if not left and not right:
            mode = "unregistered"
        elif (left and left.is_connected) and (right and right.is_connected):
            mode = "both_connected"
        elif (left and left.is_connected) or (right and right.is_connected):
            mode = "single_foot"
        else:
            mode = "disconnected"

        return InsolePairSummaryResponse(left=left, right=right, connection_mode=mode)

    @staticmethod
    async def register_device(
        db: AsyncSession,
        user_id: UUID,
        payload: InsoleRegisterRequest,
    ) -> InsoleDeviceResponse:
        row = await DeviceRepository.upsert_device(
            db,
            str(user_id),
            payload.side.value,
            payload.device_identifier,
            payload.firmware_version,
        )
        return InsoleDeviceResponse(**row)

    @staticmethod
    async def update_status(
        db: AsyncSession,
        user_id: UUID,
        side: InsoleSideType,
        payload: InsoleStatusUpdateRequest,
    ) -> InsoleDeviceResponse:
        existing = await DeviceRepository.get_by_side(db, str(user_id), side.value)
        if not existing:
            raise AppError(404, "INSOLE_NOT_REGISTERED", f"{side.value} 인솔이 등록되어 있지 않습니다.")

        curr = dict(existing)
        for k, v in payload.model_dump(exclude_unset=True).items():
            curr[k] = v.value if hasattr(v, "value") else v
        curr["last_seen_at"] = datetime.now(timezone.utc)

        updated = await DeviceRepository.update_status(db, curr)
        return InsoleDeviceResponse(**updated)

    @staticmethod
    async def unregister_device(db: AsyncSession, user_id: UUID, side: InsoleSideType) -> None:
        await DeviceRepository.delete_by_side(db, str(user_id), side.value)
