-- ============================================================================
-- Pacebeat Supabase PostgreSQL Schema & Row Level Security (RLS)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Enum 타입 정의
DO $$ BEGIN
    CREATE TYPE gender_type AS ENUM ('female', 'male');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    -- 프론트엔드 src/types/onboarding.ts ExperienceLevel ('beginner' | 'occasional' | 'regular')와 1:1 일치
    CREATE TYPE running_experience_type AS ENUM ('beginner', 'occasional', 'regular');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    -- 프론트엔드 src/types/onboarding.ts WeeklyRuns ('1' | '2' | '3+')와 1:1 일치
    CREATE TYPE weekly_runs_type AS ENUM ('1', '2', '3+');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE run_mode_type AS ENUM ('gps', 'time');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE run_completion_type AS ENUM ('goal', 'partial', 'time');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE metric_status_type AS ENUM (
        'valid',
        'insufficient_data',
        'no_data',
        'gps_poor',
        'single_foot',
        'sensor_disconnected'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE insole_side_type AS ENUM ('left', 'right');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE calibration_status_type AS ENUM ('not_started', 'in_progress', 'completed', 'failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE signal_quality_type AS ENUM ('good', 'fair', 'poor', 'unavailable');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE reflection_difficulty_type AS ENUM ('easy', 'moderate', 'hard');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 공통 updated_at 자동 갱신 함수
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 2. user_profiles (프로필, 동의, 안내 설정)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.user_profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    nickname VARCHAR(10),
    birth_year SMALLINT CHECK (birth_year IS NULL OR (birth_year >= 1900 AND birth_year <= 2100)),
    gender gender_type NULL,
    height_cm NUMERIC(5, 1) NULL CHECK (height_cm IS NULL OR (height_cm >= 100 AND height_cm <= 250)),
    weight_kg NUMERIC(5, 1) NULL CHECK (weight_kg IS NULL OR (weight_kg >= 20 AND weight_kg <= 250)),
    running_experience running_experience_type NULL,
    weekly_runs weekly_runs_type NULL,

    -- 약관 동의 상태
    consent_age_over_14 BOOLEAN NOT NULL DEFAULT FALSE,
    consent_terms_of_service BOOLEAN NOT NULL DEFAULT FALSE,
    consent_privacy_policy BOOLEAN NOT NULL DEFAULT FALSE,
    consent_location_terms BOOLEAN NOT NULL DEFAULT FALSE,
    consent_marketing BOOLEAN NOT NULL DEFAULT FALSE,
    consent_policy_version VARCHAR(32) NULL,
    consented_at TIMESTAMPTZ NULL,

    -- 완료 시각
    onboarding_completed_at TIMESTAMPTZ NULL,
    profile_completed_at TIMESTAMPTZ NULL,

    -- 음성·진동 안내 설정
    voice_guidance_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    vibration_guidance_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    guidance_frequency_km NUMERIC(3, 1) NOT NULL DEFAULT 1.0,
    vibration_intensity VARCHAR(16) NOT NULL DEFAULT 'medium',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_user_profiles_updated_at
BEFORE UPDATE ON public.user_profiles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- 3. user_baselines (기초 측정 및 개인 기준)
--    미측정·건너뛰기·120초 미만 시 값은 0이 아닌 NULL로 저장
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.user_baselines (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    skipped BOOLEAN NOT NULL DEFAULT FALSE,
    quality_status metric_status_type NOT NULL DEFAULT 'no_data',
    baseline_pace_sec_per_km INTEGER NULL CHECK (baseline_pace_sec_per_km IS NULL OR baseline_pace_sec_per_km > 0),
    cadence_spm INTEGER NULL CHECK (cadence_spm IS NULL OR cadence_spm > 0),
    stride_length_cm NUMERIC(5, 1) NULL CHECK (stride_length_cm IS NULL OR stride_length_cm > 0),
    valid_duration_ms INTEGER NULL CHECK (valid_duration_ms IS NULL OR valid_duration_ms >= 0),
    distance_m NUMERIC(8, 2) NULL CHECK (distance_m IS NULL OR distance_m >= 0),
    measured_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_user_baselines_updated_at
BEFORE UPDATE ON public.user_baselines
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- 4. insole_devices (선택형 스마트 인솔 좌·우 기기 상태)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.insole_devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    side insole_side_type NOT NULL,
    device_identifier VARCHAR(128) NOT NULL,
    is_connected BOOLEAN NOT NULL DEFAULT FALSE,
    battery_pct SMALLINT NULL CHECK (battery_pct IS NULL OR (battery_pct >= 0 AND battery_pct <= 100)),
    firmware_version VARCHAR(32) NULL,
    calibration_status calibration_status_type NOT NULL DEFAULT 'not_started',
    signal_quality signal_quality_type NOT NULL DEFAULT 'unavailable',
    last_seen_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_insole_devices_user_side UNIQUE (user_id, side)
);

CREATE INDEX IF NOT EXISTS idx_insole_devices_user_id ON public.insole_devices(user_id);

CREATE TRIGGER trg_insole_devices_updated_at
BEFORE UPDATE ON public.insole_devices
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- 5. music_presets (음악·BPM 프리셋 카탈로그)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.music_presets (
    track_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    subtitle VARCHAR(200) NULL,
    bpm INTEGER NOT NULL CHECK (bpm > 0),
    recommended_pace_sec_per_km INTEGER NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order SMALLINT NOT NULL DEFAULT 0
);

INSERT INTO public.music_presets (track_id, title, subtitle, bpm, recommended_pace_sec_per_km, sort_order)
VALUES
    -- 프론트엔드 src/features/running/music.ts MUSIC_TRACKS 4곡과 ID·제목·BPM 1:1 일치
    ('morning-stride', 'Morning Stride', '상쾌한 아침 러닝을 여는 경쾌한 리듬', 158, 420, 1),
    ('city-loop', 'City Loop', '도심 페이스를 일정하게 유지해 주는 비트', 156, 435, 2),
    ('easy-tempo', 'Easy Tempo', '호흡과 발걸음을 안정시키는 템포', 160, 400, 3),
    ('night-pace', 'Night Pace', '저녁 러닝에 어울리는 편안한 그루브', 150, 450, 4)
ON CONFLICT (track_id) DO NOTHING;

-- ============================================================================
-- 6. run_sessions (일반 러닝 세션 & 러닝 리포트)
--    client_session_id로 오프라인 재시도 멱등성 보장
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.run_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    client_session_id VARCHAR(128) NOT NULL,

    mode run_mode_type NOT NULL,
    completion run_completion_type NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    elapsed_ms INTEGER NOT NULL CHECK (elapsed_ms > 0),

    -- 목표 (TIME 모드는 NULL)
    target_distance_km NUMERIC(4, 1) NULL CHECK (target_distance_km IS NULL OR target_distance_km > 0),
    target_duration_sec INTEGER NULL CHECK (target_duration_sec IS NULL OR target_duration_sec > 0),
    target_pace_sec_per_km INTEGER NULL CHECK (target_pace_sec_per_km IS NULL OR target_pace_sec_per_km > 0),

    -- 측정 결과 (측정 실패·TIME 모드는 0이 아닌 NULL)
    distance_m NUMERIC(9, 2) NULL CHECK (distance_m IS NULL OR distance_m >= 0),
    avg_pace_sec_per_km INTEGER NULL CHECK (avg_pace_sec_per_km IS NULL OR avg_pace_sec_per_km > 0),
    cadence_spm INTEGER NULL CHECK (cadence_spm IS NULL OR cadence_spm > 0),
    step_count INTEGER NULL CHECK (step_count IS NULL OR step_count >= 0),
    target_pace_keep_ratio_pct NUMERIC(5, 2) NULL CHECK (
        target_pace_keep_ratio_pct IS NULL OR (target_pace_keep_ratio_pct >= 0 AND target_pace_keep_ratio_pct <= 100)
    ),

    -- 명시적 측정 상태 코드
    pace_status metric_status_type NOT NULL DEFAULT 'valid',
    cadence_status metric_status_type NOT NULL DEFAULT 'no_data',

    music_track_id VARCHAR(64) NULL,
    gps_gaps JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- 러닝 리포트(회고)
    reflection_difficulty reflection_difficulty_type NULL,
    reflection_reasons TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    reflection_memo VARCHAR(100) NOT NULL DEFAULT '',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_run_sessions_user_client_session UNIQUE (user_id, client_session_id)
);

CREATE INDEX IF NOT EXISTS idx_run_sessions_user_started_at
    ON public.run_sessions(user_id, started_at DESC);

CREATE TRIGGER trg_run_sessions_updated_at
BEFORE UPDATE ON public.run_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- 7. run_splits (1km 구간별 기록)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.run_splits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES public.run_sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    split_index SMALLINT NOT NULL CHECK (split_index >= 1),
    distance_m NUMERIC(7, 2) NOT NULL CHECK (distance_m > 0),
    duration_ms INTEGER NOT NULL CHECK (duration_ms > 0),
    pace_sec_per_km INTEGER NULL CHECK (pace_sec_per_km IS NULL OR pace_sec_per_km > 0),
    CONSTRAINT uq_run_splits_run_index UNIQUE (run_id, split_index)
);

CREATE INDEX IF NOT EXISTS idx_run_splits_run_id ON public.run_splits(run_id);

-- ============================================================================
-- 8. run_posture_reports (스마트 인솔 연결 세션 전용 선택적 자세 리포트)
--    인솔 미구매·미연결 러닝에는 행 자체를 생성하지 않음 (추정치 생성 금지)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.run_posture_reports (
    run_id UUID PRIMARY KEY REFERENCES public.run_sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    posture_status metric_status_type NOT NULL,
    left_connected BOOLEAN NOT NULL DEFAULT FALSE,
    right_connected BOOLEAN NOT NULL DEFAULT FALSE,

    -- 접지 시간 (측정 불가 또는 반대쪽만 연결된 발은 NULL)
    ground_contact_time_left_ms INTEGER NULL CHECK (ground_contact_time_left_ms IS NULL OR ground_contact_time_left_ms > 0),
    ground_contact_time_right_ms INTEGER NULL CHECK (ground_contact_time_right_ms IS NULL OR ground_contact_time_right_ms > 0),

    -- 양발 하중 비율 (single_foot 상태일 때는 반드시 둘 다 NULL)
    left_load_ratio_pct NUMERIC(5, 2) NULL CHECK (left_load_ratio_pct IS NULL OR (left_load_ratio_pct >= 0 AND left_load_ratio_pct <= 100)),
    right_load_ratio_pct NUMERIC(5, 2) NULL CHECK (right_load_ratio_pct IS NULL OR (right_load_ratio_pct >= 0 AND right_load_ratio_pct <= 100)),

    -- 압력 분포(앞꿈치/중족부/뒤꿈치) 및 착지 패턴
    left_pressure_distribution JSONB NULL,
    right_pressure_distribution JSONB NULL,
    left_landing_pattern VARCHAR(32) NULL,
    right_landing_pattern VARCHAR(32) NULL,
    feedback_items JSONB NOT NULL DEFAULT '[]'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_single_foot_no_bilateral_ratio CHECK (
        posture_status <> 'single_foot'
        OR (left_load_ratio_pct IS NULL AND right_load_ratio_pct IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_run_posture_reports_user_id ON public.run_posture_reports(user_id);

-- ============================================================================
-- 9. Row Level Security (RLS) 정책 설정 (auth.uid() = user_id)
-- ============================================================================
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_baselines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.insole_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.music_presets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.run_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.run_splits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.run_posture_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY pol_user_profiles_owner ON public.user_profiles
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY pol_user_baselines_owner ON public.user_baselines
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY pol_insole_devices_owner ON public.insole_devices
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY pol_music_presets_read_all ON public.music_presets
    FOR SELECT USING (TRUE);

CREATE POLICY pol_run_sessions_owner ON public.run_sessions
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY pol_run_splits_owner ON public.run_splits
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE POLICY pol_run_posture_reports_owner ON public.run_posture_reports
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
