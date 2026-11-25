import json
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AppError
from app.schemas.run import (
    GpsGapPayload,
    MusicPresetResponse,
    PostureReportPayload,
    RunCreateRequest,
    RunDetailResponse,
    RunReflectionPayload,
    RunSplitPayload,
    TargetValidateRequest,
    TargetValidateResponse,
)
from app.services.recommendation_service import compute_segment_paces

# 프론트엔드 목표 페이스 정책(4:00/km = 240초 ~ 10:00/km = 600초)과 동일한 기준
MIN_REALISTIC_PACE_SEC_PER_KM = 240
MAX_REALISTIC_PACE_SEC_PER_KM = 600


class RunService:
    @staticmethod
    def validate_target(payload: TargetValidateRequest) -> TargetValidateResponse:
        pace_sec = round(payload.target_duration_sec / payload.target_distance_km)
        segments = compute_segment_paces(pace_sec)
        trigger_m = round(payload.target_distance_km * 1000.0 * 0.85, 2)
        freeze_m = round(payload.target_distance_km * 1000.0 * 0.95, 2)

        if pace_sec < MIN_REALISTIC_PACE_SEC_PER_KM:
            return TargetValidateResponse(
                target_distance_km=payload.target_distance_km,
                target_duration_sec=payload.target_duration_sec,
                target_pace_sec_per_km=pace_sec,
                is_realistic=False,
                warning_code="PACE_TOO_FAST",
                warning_message="목표 페이스가 4:00/km보다 빠릅니다. 무리 없는 페이스로 조정해 보세요.",
                warmup_pace_sec_per_km=segments.warmup_pace_sec_per_km,
                rhythm_pace_sec_per_km=segments.rhythm_pace_sec_per_km,
                realtime_initial_pace_sec_per_km=segments.realtime_initial_pace_sec_per_km,
                realtime_trigger_distance_m=trigger_m,
                realtime_freeze_distance_m=freeze_m,
            )
        if pace_sec > MAX_REALISTIC_PACE_SEC_PER_KM:
            return TargetValidateResponse(
                target_distance_km=payload.target_distance_km,
                target_duration_sec=payload.target_duration_sec,
                target_pace_sec_per_km=pace_sec,
                is_realistic=False,
                warning_code="PACE_TOO_SLOW",
                warning_message="목표 페이스가 10:00/km보다 느립니다. 목표 시간을 확인해 주세요.",
                warmup_pace_sec_per_km=segments.warmup_pace_sec_per_km,
                rhythm_pace_sec_per_km=segments.rhythm_pace_sec_per_km,
                realtime_initial_pace_sec_per_km=segments.realtime_initial_pace_sec_per_km,
                realtime_trigger_distance_m=trigger_m,
                realtime_freeze_distance_m=freeze_m,
            )
        return TargetValidateResponse(
            target_distance_km=payload.target_distance_km,
            target_duration_sec=payload.target_duration_sec,
            target_pace_sec_per_km=pace_sec,
            is_realistic=True,
            warning_code=None,
            warning_message=None,
            warmup_pace_sec_per_km=segments.warmup_pace_sec_per_km,
            rhythm_pace_sec_per_km=segments.rhythm_pace_sec_per_km,
            realtime_initial_pace_sec_per_km=segments.realtime_initial_pace_sec_per_km,
            realtime_trigger_distance_m=trigger_m,
            realtime_freeze_distance_m=freeze_m,
        )

    @staticmethod
    async def list_music_presets(db: AsyncSession) -> list[MusicPresetResponse]:
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
        return [MusicPresetResponse(**dict(row._mapping)) for row in result]

    @staticmethod
    async def upsert_run_session(
        db: AsyncSession,
        user_id: UUID,
        payload: RunCreateRequest,
    ) -> RunDetailResponse:
        target_pace_sec = (
            round(payload.target_duration_sec / payload.target_distance_km)
            if payload.target_distance_km and payload.target_duration_sec
            else None
        )
        reflection = payload.reflection or RunReflectionPayload()

        # 1. client_session_id 기준 멱등(Idempotent) Upsert
        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO public.run_sessions (
                        user_id, client_session_id, mode, completion,
                        started_at, ended_at, elapsed_ms,
                        target_distance_km, target_duration_sec, target_pace_sec_per_km,
                        distance_m, avg_pace_sec_per_km, cadence_spm, step_count,
                        target_pace_keep_ratio_pct, pace_status, cadence_status,
                        music_track_id, gps_gaps,
                        reflection_difficulty, reflection_reasons, reflection_memo
                    ) VALUES (
                        :user_id, :client_session_id, :mode, :completion,
                        :started_at, :ended_at, :elapsed_ms,
                        :target_distance_km, :target_duration_sec, :target_pace_sec_per_km,
                        :distance_m, :avg_pace_sec_per_km, :cadence_spm, :step_count,
                        :target_pace_keep_ratio_pct, :pace_status, :cadence_status,
                        :music_track_id, CAST(:gps_gaps AS jsonb),
                        :reflection_difficulty, :reflection_reasons, :reflection_memo
                    )
                    ON CONFLICT (user_id, client_session_id) DO UPDATE SET
                        ended_at = EXCLUDED.ended_at,
                        elapsed_ms = EXCLUDED.elapsed_ms,
                        distance_m = EXCLUDED.distance_m,
                        avg_pace_sec_per_km = EXCLUDED.avg_pace_sec_per_km,
                        cadence_spm = EXCLUDED.cadence_spm,
                        step_count = EXCLUDED.step_count,
                        target_pace_keep_ratio_pct = EXCLUDED.target_pace_keep_ratio_pct,
                        pace_status = EXCLUDED.pace_status,
                        cadence_status = EXCLUDED.cadence_status,
                        gps_gaps = EXCLUDED.gps_gaps,
                        reflection_difficulty = EXCLUDED.reflection_difficulty,
                        reflection_reasons = EXCLUDED.reflection_reasons,
                        reflection_memo = EXCLUDED.reflection_memo
                    RETURNING id
                    """
                ),
                {
                    "user_id": str(user_id),
                    "client_session_id": payload.client_session_id,
                    "mode": payload.mode.value,
                    "completion": payload.completion.value,
                    "started_at": payload.started_at,
                    "ended_at": payload.ended_at,
                    "elapsed_ms": payload.elapsed_ms,
                    "target_distance_km": payload.target_distance_km,
                    "target_duration_sec": payload.target_duration_sec,
                    "target_pace_sec_per_km": target_pace_sec,
                    "distance_m": payload.distance_m,
                    "avg_pace_sec_per_km": payload.avg_pace_sec_per_km,
                    "cadence_spm": payload.cadence_spm,
                    "step_count": payload.step_count,
                    "target_pace_keep_ratio_pct": payload.target_pace_keep_ratio_pct,
                    "pace_status": payload.pace_status.value,
                    "cadence_status": payload.cadence_status.value,
                    "music_track_id": payload.music_track_id,
                    "gps_gaps": json.dumps([g.model_dump() for g in payload.gps_gaps]),
                    "reflection_difficulty": reflection.difficulty.value if reflection.difficulty else None,
                    "reflection_reasons": [r.value for r in reflection.reasons],
                    "reflection_memo": reflection.memo,
                },
            )
        ).first()

        run_id = UUID(str(row._mapping["id"]))

        # 2. 구간 기록(run_splits) 교체 저장
        await db.execute(text("DELETE FROM public.run_splits WHERE run_id = :run_id"), {"run_id": str(run_id)})
        for split in payload.splits:
            await db.execute(
                text(
                    """
                    INSERT INTO public.run_splits (
                        run_id, user_id, split_index, distance_m, duration_ms, pace_sec_per_km
                    ) VALUES (
                        :run_id, :user_id, :split_index, :distance_m, :duration_ms, :pace_sec_per_km
                    )
                    """
                ),
                {
                    "run_id": str(run_id),
                    "user_id": str(user_id),
                    "split_index": split.index,
                    "distance_m": split.distance_m,
                    "duration_ms": split.duration_ms,
                    "pace_sec_per_km": split.pace_sec_per_km,
                },
            )

        # 3. 선택적 자세 리포트(run_posture_reports): 인솔 연결 데이터가 전달된 세션에만 생성
        if payload.posture_report is not None and (
            payload.posture_report.left_connected or payload.posture_report.right_connected
        ):
            pr = payload.posture_report
            await db.execute(
                text(
                    """
                    INSERT INTO public.run_posture_reports (
                        run_id, user_id, posture_status, left_connected, right_connected,
                        ground_contact_time_left_ms, ground_contact_time_right_ms,
                        left_load_ratio_pct, right_load_ratio_pct,
                        left_pressure_distribution, right_pressure_distribution,
                        left_landing_pattern, right_landing_pattern, feedback_items
                    ) VALUES (
                        :run_id, :user_id, :posture_status, :left_connected, :right_connected,
                        :gct_left, :gct_right, :load_left, :load_right,
                        CAST(:press_left AS jsonb), CAST(:press_right AS jsonb),
                        :landing_left, :landing_right, CAST(:feedback_items AS jsonb)
                    )
                    ON CONFLICT (run_id) DO UPDATE SET
                        posture_status = EXCLUDED.posture_status,
                        left_connected = EXCLUDED.left_connected,
                        right_connected = EXCLUDED.right_connected,
                        ground_contact_time_left_ms = EXCLUDED.ground_contact_time_left_ms,
                        ground_contact_time_right_ms = EXCLUDED.ground_contact_time_right_ms,
                        left_load_ratio_pct = EXCLUDED.left_load_ratio_pct,
                        right_load_ratio_pct = EXCLUDED.right_load_ratio_pct,
                        left_pressure_distribution = EXCLUDED.left_pressure_distribution,
                        right_pressure_distribution = EXCLUDED.right_pressure_distribution,
                        left_landing_pattern = EXCLUDED.left_landing_pattern,
                        right_landing_pattern = EXCLUDED.right_landing_pattern,
                        feedback_items = EXCLUDED.feedback_items
                    """
                ),
                {
                    "run_id": str(run_id),
                    "user_id": str(user_id),
                    "posture_status": pr.posture_status.value,
                    "left_connected": pr.left_connected,
                    "right_connected": pr.right_connected,
                    "gct_left": pr.ground_contact_time_left_ms,
                    "gct_right": pr.ground_contact_time_right_ms,
                    "load_left": pr.left_load_ratio_pct,
                    "load_right": pr.right_load_ratio_pct,
                    "press_left": json.dumps(pr.left_pressure_distribution.model_dump())
                    if pr.left_pressure_distribution
                    else None,
                    "press_right": json.dumps(pr.right_pressure_distribution.model_dump())
                    if pr.right_pressure_distribution
                    else None,
                    "landing_left": pr.left_landing_pattern,
                    "landing_right": pr.right_landing_pattern,
                    "feedback_items": json.dumps(pr.feedback_items),
                },
            )

        await db.commit()
        return await RunService.get_run_detail(db, user_id, run_id)

    @staticmethod
    async def get_run_detail(db: AsyncSession, user_id: UUID, run_id: UUID) -> RunDetailResponse:
        row = (
            await db.execute(
                text(
                    """
                    SELECT s.*,
                           p.posture_status, p.left_connected, p.right_connected,
                           p.ground_contact_time_left_ms, p.ground_contact_time_right_ms,
                           p.left_load_ratio_pct, p.right_load_ratio_pct,
                           p.left_pressure_distribution, p.right_pressure_distribution,
                           p.left_landing_pattern, p.right_landing_pattern, p.feedback_items
                    FROM public.run_sessions s
                    LEFT JOIN public.run_posture_reports p ON p.run_id = s.id
                    WHERE s.id = :run_id AND s.user_id = :user_id
                    """
                ),
                {"run_id": str(run_id), "user_id": str(user_id)},
            )
        ).first()

        if not row:
            raise AppError(404, "RUN_NOT_FOUND", "해당 러닝 기록을 찾을 수 없습니다.")

        m = row._mapping
        splits_rows = await db.execute(
            text(
                """
                SELECT split_index AS index, distance_m, duration_ms, pace_sec_per_km
                FROM public.run_splits
                WHERE run_id = :run_id
                ORDER BY split_index ASC
                """
            ),
            {"run_id": str(run_id)},
        )
        splits = [RunSplitPayload(**dict(r._mapping)) for r in splits_rows]

        has_posture = m["posture_status"] is not None
        posture_report = (
            PostureReportPayload(
                posture_status=m["posture_status"],
                left_connected=m["left_connected"],
                right_connected=m["right_connected"],
                ground_contact_time_left_ms=m["ground_contact_time_left_ms"],
                ground_contact_time_right_ms=m["ground_contact_time_right_ms"],
                left_load_ratio_pct=float(m["left_load_ratio_pct"]) if m["left_load_ratio_pct"] is not None else None,
                right_load_ratio_pct=float(m["right_load_ratio_pct"]) if m["right_load_ratio_pct"] is not None else None,
                left_pressure_distribution=m["left_pressure_distribution"],
                right_pressure_distribution=m["right_pressure_distribution"],
                left_landing_pattern=m["left_landing_pattern"],
                right_landing_pattern=m["right_landing_pattern"],
                feedback_items=m["feedback_items"] or [],
            )
            if has_posture
            else None
        )

        return RunDetailResponse(
            run_id=m["id"],
            client_session_id=m["client_session_id"],
            mode=m["mode"],
            completion=m["completion"],
            started_at=m["started_at"],
            ended_at=m["ended_at"],
            elapsed_ms=m["elapsed_ms"],
            target_distance_km=float(m["target_distance_km"]) if m["target_distance_km"] is not None else None,
            target_duration_sec=m["target_duration_sec"],
            target_pace_sec_per_km=m["target_pace_sec_per_km"],
            distance_m=float(m["distance_m"]) if m["distance_m"] is not None else None,
            avg_pace_sec_per_km=m["avg_pace_sec_per_km"],
            pace_status=m["pace_status"],
            cadence_spm=m["cadence_spm"],
            cadence_status=m["cadence_status"],
            step_count=m["step_count"],
            target_pace_keep_ratio_pct=float(m["target_pace_keep_ratio_pct"])
            if m["target_pace_keep_ratio_pct"] is not None
            else None,
            music_track_id=m["music_track_id"],
            has_posture_report=has_posture,
            splits=splits,
            gps_gaps=[GpsGapPayload(**g) for g in (m["gps_gaps"] or [])],
            reflection=RunReflectionPayload(
                difficulty=m["reflection_difficulty"],
                reasons=m["reflection_reasons"] or [],
                memo=m["reflection_memo"] or "",
            ),
            posture_report=posture_report,
        )
