from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import AuthenticatedUser, get_current_user
from app.schemas.run import (
    MusicPresetResponse,
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
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> list[RunSummaryItemResponse]:
    # 기록이 없는 날짜를 0으로 채우지 않고 실제 존재하는 세션만 반환
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
        {"user_id": str(user.user_id), "from_dt": from_dt, "to_dt": to_dt},
    )
    return [RunSummaryItemResponse(**dict(r._mapping)) for r in rows]


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
async def delete_run_session(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> None:
    res = await db.execute(
        text("DELETE FROM public.run_sessions WHERE id = :run_id AND user_id = :user_id RETURNING id"),
        {"run_id": str(run_id), "user_id": str(user.user_id)},
    )
    if not res.first():
        raise AppError(404, "RUN_NOT_FOUND", "해당 러닝 기록을 찾을 수 없습니다.")
    await db.commit()