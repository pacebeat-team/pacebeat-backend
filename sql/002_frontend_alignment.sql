-- ============================================================================
-- 002_frontend_alignment.sql
-- 프론트엔드 안내 설정(beatGuide, frequency, autoPause) 및 증분 동기화 인덱스 추가
-- ============================================================================

DO $$ BEGIN
    -- 프론트엔드 src/features/my/guidanceSettings.ts GuidanceFrequency ('perKm' | 'offPace' | 'both')
    CREATE TYPE guidance_frequency_mode_type AS ENUM ('perKm', 'offPace', 'both');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE public.user_profiles
    ADD COLUMN IF NOT EXISTS beat_guidance_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS guidance_frequency_mode guidance_frequency_mode_type NOT NULL DEFAULT 'offPace',
    ADD COLUMN IF NOT EXISTS auto_pause_enabled BOOLEAN NOT NULL DEFAULT TRUE;

-- 증분 동기화(updated_since) 및 client_session_id 조회 최적화 인덱스
CREATE INDEX IF NOT EXISTS idx_run_sessions_user_updated_at
    ON public.run_sessions(user_id, updated_at DESC);
