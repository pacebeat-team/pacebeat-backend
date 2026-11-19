from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import AuthenticatedUser, get_current_user
from app.schemas.common import InsoleSideType
from app.schemas.device import (
    InsoleDeviceResponse,
    InsolePairSummaryResponse,
    InsoleRegisterRequest,
    InsoleStatusUpdateRequest,
)

router = APIRouter(prefix="/api/v1/devices/insoles", tags=["My - Smart Insoles"])


@router.get("", response_model=InsolePairSummaryResponse)
async def get_insole_pair_status(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> InsolePairSummaryResponse:
    rows = await db.execute(
        text("SELECT * FROM public.insole_devices WHERE user_id = :user_id"),
        {"user_id": str(user.user_id)},
    )
    by_side: dict[str, InsoleDeviceResponse] = {}
    for r in rows:
        m = r._mapping
        by_side[m["side"]] = InsoleDeviceResponse(**dict(m))

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


@router.post("", response_model=InsoleDeviceResponse, status_code=status.HTTP_201_CREATED)
async def register_insole_device(
    payload: InsoleRegisterRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> InsoleDeviceResponse:
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
                "user_id": str(user.user_id),
                "side": payload.side.value,
                "device_identifier": payload.device_identifier,
                "firmware_version": payload.firmware_version,
                "now": datetime.now(timezone.utc),
            },
        )
    ).first()
    await db.commit()
    return InsoleDeviceResponse(**dict(row._mapping))


@router.patch("/{side}", response_model=InsoleDeviceResponse)
async def update_insole_status(
    side: InsoleSideType,
    payload: InsoleStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> InsoleDeviceResponse:
    existing = (
        await db.execute(
            text("SELECT * FROM public.insole_devices WHERE user_id = :user_id AND side = :side"),
            {"user_id": str(user.user_id), "side": side.value},
        )
    ).first()
    if not existing:
        raise AppError(404, "INSOLE_NOT_REGISTERED", f"{side.value} 인솔이 등록되어 있지 않습니다.")

    curr = dict(existing._mapping)
    for k, v in payload.model_dump(exclude_unset=True).items():
        curr[k] = v.value if hasattr(v, "value") else v
    curr["last_seen_at"] = datetime.now(timezone.utc)

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
            curr,
        )
    ).first()
    await db.commit()
    return InsoleDeviceResponse(**dict(updated._mapping))


@router.delete("/{side}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_insole_device(
    side: InsoleSideType,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Response:
    await db.execute(
        text("DELETE FROM public.insole_devices WHERE user_id = :user_id AND side = :side"),
        {"user_id": str(user.user_id), "side": side.value},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
