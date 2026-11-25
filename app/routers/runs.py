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
