# Pacebeat Backend API 개발 명세서 (FastAPI + Supabase + Koyeb)

> 본 문서는 **Pacebeat** 프론트엔드(5탭 정보구조: 홈 / 러닝 / 기록 / 성장 / 마이)와 연동되는 백엔드 서버를 별도 프로젝트 폴더(`pacebeat-backend`)에서 바로 구축·배포할 수 있도록 작성된 **실무 실행용 전체 개발 명세서**입니다.
> 새 프로젝트 폴더에 이 파일을 복사한 뒤, AI 코딩 에이전트에게 `"이 명세서의 1~5단계를 그대로 파일로 생성하고 설정해 줘"`라고 지시하면 즉시 실행 가능한 서버가 완성됩니다.

---

## 0. 핵심 도메인 원칙 및 아키텍처 기준 (ADR 준수)

1. **스마트폰 단독 기본 서비스 (ADR-001)**
   - 스마트 인솔 구매·연결을 시작 조건으로 요구하지 않으며, 스마트폰만으로 온보딩·기초 측정·목표 설정·러닝·기록·성장 기능을 모두 사용할 수 있어야 합니다.
2. **러닝 리포트와 자세 리포트의 엄격한 분리**
   - 모든 러닝 세션(`run_sessions`)은 **러닝 리포트**(거리, 시간, GPS 페이스, 지원 기기 한정 케이던스, 구간 기록 `run_splits`, 목표 달성도, 리포트/회고)를 가집니다.
   - **자세 리포트**(`run_posture_reports`)는 스마트 인솔이 연결되어 유효한 데이터를 수집한 세션에만 선택적(`0..1`)으로 생성됩니다.
   - 인솔 미구매·미연결 시 자세 점수를 절대 추정하지 않으며, 추후 인솔을 연결해도 과거 러닝 세션에 자세 데이터가 소급 생성되지 않습니다.
   - 한쪽 인솔만 유효한 경우 양발 비교 지표(`left_load_ratio_pct`, `right_load_ratio_pct`)를 `null`로 비우고 `posture_status = 'single_foot'`으로 저장·응답합니다.
3. **결측치 및 예외 상태 표현 원칙 (ADR-003, ADR-004)**
   - 모든 페이스(Pace)는 내부 및 DB에 **`sec/km` 정수**(예: `5'30"/km` → `330`)로 저장합니다.
   - 측정 실패, 걸음 수 없음, GPS 불량, TIME 모드(거리 미측정), 데이터 부족, 휴식일 등은 **절대 `0`이나 정상 값으로 저장·반환하지 않습니다.**
   - 반드시 **`null`**과 명시적 상태 코드(`valid`, `insufficient_data`, `no_data`, `gps_poor`, `single_foot`, `sensor_disconnected`)로 구분해 응답합니다.
   - `TIME` 모드(`mode = 'time'`) 기록은 거리(`distance_m = null`)와 페이스(`avg_pace_sec_per_km = null`)를 가지지 않으며, 누적 거리 합계 및 거리 완주 집계에서 제외합니다.
4. **오프라인 및 네트워크 재시도 멱등성(Idempotency)**
   - 러닝 종료 후 저장 재시도 시 중복 레코드가 생성되지 않도록 `(user_id, client_session_id)` 유니크 제약과 **Upsert(멱등 저장)**를 지원합니다. (프론트엔드의 `recordId` / `sessionId`와 1:1 매핑)

---

## 1단계. 전체 프로젝트 디렉토리 구조 및 API 엔드포인트 명세표

### 1-1. 프로젝트 디렉토리 구조

```text
pacebeat-backend/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI 앱 진입점, CORS, 예외 핸들러, 라우터 등록
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py               # pydantic-settings 기반 환경변수 관리
│   │   ├── database.py             # SQLAlchemy 2.0 AsyncEngine, AsyncSession (asyncpg)
│   │   ├── errors.py               # 표준 에러 응답 스키마 및 전역 Exception Handler
│   │   └── security.py             # Supabase Auth JWT 검증 및 get_current_user 의존성
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py               # GET /health (Koyeb 헬스체크)
│   │   ├── users.py                # 마이(My): 프로필, 동의, 기초 측정(baseline), 안내 설정, 데이터 관리
│   │   ├── devices.py              # 마이(My): 스마트 인솔 좌/우 기기 등록·상태·보정·해제
│   │   ├── home.py                 # 홈(Home): 대시보드 통합 요약 조회
│   │   ├── runs.py                 # 러닝(Running) & 기록(Records): 목표 검증, 음악 프리셋, 세션 저장/조회/회고
│   │   └── growth.py               # 성장(Growth): 주간·월간 러닝 성장 추이 및 자세 리포트 비교
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py               # 공통 Enum, 상태 코드, 에러 응답 스키마
│   │   ├── user.py                 # 프로필, 약관 동의, 기초 측정, 안내 설정 스키마
│   │   ├── device.py               # 스마트 인솔 좌/우 상태 및 보정 스키마
│   │   ├── home.py                 # 홈 대시보드 요약 응답 스키마
│   │   ├── run.py                  # 목표 검증, 음악 프리셋, 러닝 저장(멱등), 상세/목록, 회고 스키마
│   │   └── growth.py               # 러닝 성장 추이 및 자세 리포트 기간별 비교 스키마
│   ├── services/
│   │   ├── __init__.py
│   │   ├── user_service.py         # 프로필/기초 측정/데이터 내보내기·삭제 비즈니스 로직
│   │   ├── device_service.py       # 좌/우 인솔 페어링 및 보정 상태 관리
│   │   ├── home_service.py         # 이번 주 활동, 다음 추천 목표·페이스, 기초 측정 유도 계산
│   │   ├── run_service.py          # 목표 페이스 검증, 멱등 세션 저장, 자세 리포트 분기 생성
│   │   └── growth_service.py       # 주간/월간 러닝 집계 및 유효 인솔 세션 한정 자세 집계
│   └── repositories/
│       ├── __init__.py
│       ├── user_repo.py            # user_profiles, user_baselines DB 접근 계층
│       ├── device_repo.py          # insole_devices DB 접근 계층
│       ├── run_repo.py             # run_sessions, run_splits, run_posture_reports, music_presets DB 접근
│       └── growth_repo.py          # 기간별 집계 쿼리 계층
├── sql/
│   └── 001_init_schema_and_rls.sql # Supabase SQL Editor 실행용 DDL & RLS 스크립트
├── tests/
│   └── test_domain_rules.py        # 결측치 null 원칙, 목표 페이스 검증, single_foot 검증 단위 테스트
├── .env.example
├── Dockerfile
├── requirements.txt
└── README.md
```

### 1-2. API 엔드포인트 명세표 (5탭 정보구조 기반)

| 분류 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| **System** | `GET` | `/health` | 불필요 | Koyeb 컨테이너 헬스체크 및 DB 연결 상태 확인 |
| **My (프로필)** | `GET` | `/api/v1/users/me` | Bearer JWT | 내 프로필, 러닝 경험, 약관 동의, 안내 설정 통합 조회 |
| **My (프로필)** | `PATCH` | `/api/v1/users/me` | Bearer JWT | 프로필(닉네임, 출생연도, 성별, 키, 몸무게), 러닝 경험, 약관 동의 수정 |
| **My (기초측정)** | `GET` | `/api/v1/users/me/baseline` | Bearer JWT | 개인 기준(기준 페이스 `sec/km`, 케이던스, 보폭, 측정 품질 상태) 조회 |
| **My (기초측정)** | `PUT` | `/api/v1/users/me/baseline` | Bearer JWT | 기초 측정 결과 저장·재설정 (건너뛰기 `skipped=true` 및 120초 미만 `insufficient_data` 지원) |
| **My (안내설정)** | `PATCH` | `/api/v1/users/me/guidance` | Bearer JWT | 음성·진동 안내 켜기/끄기, 안내 빈도, 진동 강도 설정 변경 |
| **My (데이터)** | `POST` | `/api/v1/users/me/data-export` | Bearer JWT | 개인 프로필·측정·러닝·자세 데이터 전체 JSON 내보내기 |
| **My (데이터)** | `DELETE` | `/api/v1/users/me` | Bearer JWT | 계정 및 연관 러닝 데이터 전체 삭제 요청 |
| **My (인솔)** | `GET` | `/api/v1/devices/insoles` | Bearer JWT | 좌/우 스마트 인솔 등록 현황, 배터리, 연결·보정·신호 품질 상태 조회 |
| **My (인솔)** | `POST` | `/api/v1/devices/insoles` | Bearer JWT | 좌(`left`) 또는 우(`right`) 스마트 인솔 기기 등록(페어링) |
| **My (인솔)** | `PATCH` | `/api/v1/devices/insoles/{side}` | Bearer JWT | 좌/우 인솔 연결 상태, 배터리(`%`), 펌웨어, 착용 보정(`calibration_status`), 신호 품질 업데이트 |
| **My (인솔)** | `DELETE` | `/api/v1/devices/insoles/{side}` | Bearer JWT | 좌/우 스마트 인솔 연결 해제 및 기기 등록 삭제 |
| **Home** | `GET` | `/api/v1/home/summary` | Bearer JWT | 홈 대시보드 통합 조회 (이번 주 달린 요일·요약, 지난 러닝, 다음 추천 목표·페이스 및 근거, 기초 측정 유도 플래그) |
| **Running** | `POST` | `/api/v1/runs/targets/validate` | Bearer JWT | 목표 거리·시간 입력 시 목표 페이스(`sec/km`) 계산 및 비현실적 목표 경고 검증 |
| **Running** | `GET` | `/api/v1/music/presets` | Bearer JWT | 러닝 음악·박자(BPM) 프리셋 목록 조회 |
| **Running** | `POST` | `/api/v1/runs` | Bearer JWT | 러닝 세션 저장 (`client_session_id` 기반 멱등성 보장, 구간 기록 및 조건부 자세 리포트 동시 저장) |
| **Records** | `GET` | `/api/v1/runs` | Bearer JWT | 기간별(`from`, `to`) 러닝 기록 목록 조회 (기록 없는 날짜를 0으로 채우지 않음) |
| **Records** | `GET` | `/api/v1/runs/{run_id}` | Bearer JWT | 개별 러닝 상세 조회 (`has_posture_report` 플래그, 러닝 리포트, 구간 기록, 자세 리포트 반환) |
| **Records** | `PATCH` | `/api/v1/runs/{run_id}/reflection` | Bearer JWT | 러닝 리포트 회고(체감 난이도, 힘들었던 이유 배열, 100자 이내 메모) 저장·수정 |
| **Growth** | `GET` | `/api/v1/growth/running` | Bearer JWT | 주간/월간(`period=weekly\|monthly`) 러닝 성장 추이 (거리·횟수·시간, 평균 페이스, 완주율, 체감 난이도 분포) |
| **Growth** | `GET` | `/api/v1/growth/posture` | Bearer JWT | 주간/월간(`period=weekly\|monthly`) 자세 리포트 목록 및 기간별 자세 변화 비교 (인솔 유효 세션 한정) |

---

## 2단계. Supabase PostgreSQL 테이블 생성 SQL (DDL) 및 RLS 정책

아래 스크립트를 `sql/001_init_schema_and_rls.sql`로 저장하고 **Supabase SQL Editor**에서 그대로 실행합니다.

```sql
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
```

---

## 3단계. 설정 파일 (`requirements.txt`, `.env.example`, `Dockerfile`)

### 3-1. `requirements.txt`

```txt
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic==2.10.4
pydantic-settings==2.7.1
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
PyJWT[crypto]==2.10.1
httpx==0.28.1
pytest==8.3.4
```

### 3-2. `.env.example`

```dotenv
# Application
APP_NAME=pacebeat-backend
APP_ENV=development
PORT=8000
CORS_ORIGINS=["http://localhost:5173","https://pacebeat.app"]

# Supabase Project & Auth
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=your-supabase-anon-or-service-role-key
SUPABASE_JWT_SECRET=your-supabase-jwt-secret

# PostgreSQL Async Connection (Supabase Transaction/Session Pooler or Direct)
DATABASE_URL=postgresql+asyncpg://postgres.your-project-ref:your-db-password@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
```

### 3-3. `Dockerfile` (Koyeb 동적 `PORT` 및 헬스체크 최적화)

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD sh -c 'curl -fsS http://127.0.0.1:${PORT:-8000}/health || exit 1'

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
```

---

## 4단계. 핵심 FastAPI 소스 코드 (생략 없이 실행 가능한 코드)

### 4-1. `app/core/config.py`

```python
import json
from functools import lru_cache
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "pacebeat-backend"
    APP_ENV: str = "development"
    PORT: int = 8000
    CORS_ORIGINS: List[str] = ["http://localhost:5173"]

    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_JWT_SECRET: str
    DATABASE_URL: str

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | List[str]) -> List[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### 4-2. `app/core/errors.py`

```python
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    status_code: int
    error_code: str
    message: str


class AppError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorDetail(
                status_code=exc.status_code,
                error_code=exc.error_code,
                message=exc.message,
            ).model_dump(),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorDetail(
                status_code=exc.status_code,
                error_code="HTTP_ERROR",
                message=str(exc.detail),
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first_msg = exc.errors()[0].get("msg", "Invalid request payload") if exc.errors() else "Validation error"
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorDetail(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                error_code="VALIDATION_ERROR",
                message=first_msg,
            ).model_dump(),
        )
```

### 4-3. `app/core/database.py`

```python
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import get_settings

settings = get_settings()

# Supabase Transaction Pooler(6543 포트) 호환을 위해 statement_cache_size=0 설정
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={"statement_cache_size": 0},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

### 4-4. `app/core/security.py`

```python
from dataclasses import dataclass
from uuid import UUID
import jwt
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import Settings, get_settings
from app.core.errors import AppError

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    email: str | None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_MISSING_TOKEN",
            message="인증 토큰이 필요합니다.",
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        sub = payload.get("sub")
        if not sub:
            raise ValueError("Missing sub claim")
        return AuthenticatedUser(user_id=UUID(sub), email=payload.get("email"))
    except (jwt.PyJWTError, ValueError) as exc:
        raise AppError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="AUTH_INVALID_TOKEN",
            message=f"유효하지 않거나 만료된 토큰입니다: {exc}",
        ) from exc
```

### 4-5. `app/schemas/common.py`

```python
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated
from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """
    프론트엔드(TypeScript camelCase)와 백엔드(Python snake_case)를 양방향 자동 호환하는 기본 모델.
    - 요청(Request): camelCase(예: targetDistanceKm)와 snake_case(예: target_distance_km) 모두 허용
    - 응답(Response): by_alias=True 시 프론트엔드 타입 그대로 camelCase 반환
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


def _parse_epoch_or_dt(value: int | float | str | datetime | None) -> datetime | None:
    """프론트엔드의 Unix epoch ms(Date.now() 숫자)와 ISO-8601 문자열을 모두 UTC datetime으로 변환"""
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


EpochDatetime = Annotated[
    datetime,
    BeforeValidator(_parse_epoch_or_dt),
    PlainSerializer(lambda dt: int(dt.timestamp() * 1000), return_type=int, when_used="json"),
]


class GenderType(str, Enum):
    female = "female"
    male = "male"


# 프론트엔드 src/types/onboarding.ts ExperienceLevel과 1:1 일치
class RunningExperienceType(str, Enum):
    beginner = "beginner"
    occasional = "occasional"
    regular = "regular"


# 프론트엔드 src/types/onboarding.ts WeeklyRuns와 1:1 일치
class WeeklyRunsType(str, Enum):
    one = "1"
    two = "2"
    three_plus = "3+"


class RunModeType(str, Enum):
    gps = "gps"
    time = "time"


class RunCompletionType(str, Enum):
    goal = "goal"
    partial = "partial"
    time = "time"


class MetricStatusType(str, Enum):
    valid = "valid"
    insufficient_data = "insufficient_data"
    no_data = "no_data"
    gps_poor = "gps_poor"
    single_foot = "single_foot"
    sensor_disconnected = "sensor_disconnected"


class InsoleSideType(str, Enum):
    left = "left"
    right = "right"


class CalibrationStatusType(str, Enum):
    not_started = "not_started"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"


class SignalQualityType(str, Enum):
    good = "good"
    fair = "fair"
    poor = "poor"
    unavailable = "unavailable"


class ReflectionDifficultyType(str, Enum):
    easy = "easy"
    moderate = "moderate"
    hard = "hard"


class ReflectionReasonType(str, Enum):
    breath = "breath"
    legs = "legs"
    boredom = "boredom"
    time = "time"


class GrowthPeriodType(str, Enum):
    weekly = "weekly"
    monthly = "monthly"
```

### 4-6. `app/schemas/user.py` & `app/schemas/device.py`

```python
# app/schemas/user.py
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, model_validator
from app.schemas.common import GenderType, MetricStatusType, RunningExperienceType


class ConsentPayload(BaseModel):
    age_over_14: bool
    terms_of_service: bool
    privacy_policy: bool
    location_terms: bool
    marketing: bool = False
    policy_version: str | None = None
    consented_at: datetime | None = None


class GuidanceSettingsPayload(BaseModel):
    voice_guidance_enabled: bool = True
    vibration_guidance_enabled: bool = True
    guidance_frequency_km: float = Field(default=1.0, ge=0.5, le=10.0)
    vibration_intensity: str = Field(default="medium", pattern="^(low|medium|high)$")


class UserProfileUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, min_length=2, max_length=10)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    gender: GenderType | None = None
    height_cm: float | None = Field(default=None, ge=100, le=250)
    weight_kg: float | None = Field(default=None, ge=20, le=250)
    running_experience: RunningExperienceType | None = None
    consent: ConsentPayload | None = None
    onboarding_completed_at: datetime | None = None
    profile_completed_at: datetime | None = None


class UserProfileResponse(BaseModel):
    user_id: UUID
    nickname: str | None
    birth_year: int | None
    gender: GenderType | None
    height_cm: float | None
    weight_kg: float | None
    running_experience: RunningExperienceType | None
    consent: ConsentPayload
    guidance: GuidanceSettingsPayload
    onboarding_completed_at: datetime | None
    profile_completed_at: datetime | None


class BaselineUpsertRequest(BaseModel):
    skipped: bool = False
    quality_status: MetricStatusType = MetricStatusType.no_data
    baseline_pace_sec_per_km: int | None = Field(default=None, gt=0)
    cadence_spm: int | None = Field(default=None, gt=0)
    stride_length_cm: float | None = Field(default=None, gt=0)
    valid_duration_ms: int | None = Field(default=None, ge=0)
    distance_m: float | None = Field(default=None, ge=0)
    measured_at: datetime | None = None

    @model_validator(mode="after")
    def enforce_null_when_insufficient(self) -> "BaselineUpsertRequest":
        # 120초(120,000ms) 미만이거나 건너뛰기/데이터 부족이면 기준 페이스를 0이나 추정치로 두지 않고 null로 강제
        if self.skipped or self.quality_status != MetricStatusType.valid:
            self.baseline_pace_sec_per_km = None
        if self.valid_duration_ms is not None and self.valid_duration_ms < 120_000:
            self.quality_status = MetricStatusType.insufficient_data
            self.baseline_pace_sec_per_km = None
        return self


class BaselineResponse(BaseModel):
    user_id: UUID
    skipped: bool
    quality_status: MetricStatusType
    baseline_pace_sec_per_km: int | None
    cadence_spm: int | None
    stride_length_cm: float | None
    valid_duration_ms: int | None
    distance_m: float | None
    measured_at: datetime | None
```

```python
# app/schemas/device.py
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from app.schemas.common import CalibrationStatusType, InsoleSideType, SignalQualityType


class InsoleRegisterRequest(BaseModel):
    side: InsoleSideType
    device_identifier: str = Field(..., min_length=2, max_length=128)
    firmware_version: str | None = None


class InsoleStatusUpdateRequest(BaseModel):
    is_connected: bool | None = None
    battery_pct: int | None = Field(default=None, ge=0, le=100)
    firmware_version: str | None = None
    calibration_status: CalibrationStatusType | None = None
    signal_quality: SignalQualityType | None = None


class InsoleDeviceResponse(BaseModel):
    id: UUID
    side: InsoleSideType
    device_identifier: str
    is_connected: bool
    battery_pct: int | None
    firmware_version: str | None
    calibration_status: CalibrationStatusType
    signal_quality: SignalQualityType
    last_seen_at: datetime | None


class InsolePairSummaryResponse(BaseModel):
    left: InsoleDeviceResponse | None
    right: InsoleDeviceResponse | None
    connection_mode: str  # "both_connected" | "single_foot" | "disconnected" | "unregistered"
```

### 4-7. `app/schemas/run.py`, `app/schemas/home.py`, `app/schemas/growth.py`

```python
# app/schemas/run.py
from datetime import datetime
from typing import List
from uuid import UUID
from pydantic import BaseModel, Field, model_validator
from app.schemas.common import (
    MetricStatusType,
    ReflectionDifficultyType,
    ReflectionReasonType,
    RunCompletionType,
    RunModeType,
)


class TargetValidateRequest(BaseModel):
    target_distance_km: float = Field(..., gt=0, le=42.2)
    target_duration_sec: int = Field(..., gt=0)


class TargetValidateResponse(BaseModel):
    target_distance_km: float
    target_duration_sec: int
    target_pace_sec_per_km: int
    is_realistic: bool
    warning_code: str | None  # None | "PACE_TOO_FAST" | "PACE_TOO_SLOW"
    warning_message: str | None


class MusicPresetResponse(CamelModel):
    # 프론트엔드 MusicTrack { id, title, bpm }과 1:1 호환되도록 id 프로퍼티 제공
    track_id: str = Field(..., serialization_alias="id", validation_alias="id")
    title: str
    subtitle: str | None = None
    bpm: int
    recommended_pace_sec_per_km: int | None = None


class RunSplitPayload(BaseModel):
    index: int = Field(..., ge=1)
    distance_m: float = Field(..., gt=0)
    duration_ms: int = Field(..., gt=0)
    pace_sec_per_km: int | None = Field(default=None, gt=0)


class GpsGapPayload(BaseModel):
    lost_at_ms: int = Field(..., ge=0)
    recovered_at_ms: int | None = Field(default=None, ge=0)


class RunReflectionPayload(BaseModel):
    difficulty: ReflectionDifficultyType | None = None
    reasons: List[ReflectionReasonType] = Field(default_factory=list)
    memo: str = Field(default="", max_length=100)


class PressureDistributionPayload(BaseModel):
    forefoot_pct: float = Field(..., ge=0, le=100)
    midfoot_pct: float = Field(..., ge=0, le=100)
    heel_pct: float = Field(..., ge=0, le=100)


class PostureReportPayload(BaseModel):
    posture_status: MetricStatusType
    left_connected: bool
    right_connected: bool
    ground_contact_time_left_ms: int | None = Field(default=None, gt=0)
    ground_contact_time_right_ms: int | None = Field(default=None, gt=0)
    left_load_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    right_load_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    left_pressure_distribution: PressureDistributionPayload | None = None
    right_pressure_distribution: PressureDistributionPayload | None = None
    left_landing_pattern: str | None = None
    right_landing_pattern: str | None = None
    feedback_items: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_single_foot_and_missing(self) -> "PostureReportPayload":
        # 한쪽 인솔만 연결된 경우 single_foot 상태로 강제하고 양발 하중 비교 지표를 숨김(null)
        if self.left_connected != self.right_connected:
            self.posture_status = MetricStatusType.single_foot
        if self.posture_status == MetricStatusType.single_foot:
            self.left_load_ratio_pct = None
            self.right_load_ratio_pct = None
            if not self.left_connected:
                self.ground_contact_time_left_ms = None
                self.left_pressure_distribution = None
                self.left_landing_pattern = None
            if not self.right_connected:
                self.ground_contact_time_right_ms = None
                self.right_pressure_distribution = None
                self.right_landing_pattern = None
        return self


class RunCreateRequest(BaseModel):
    client_session_id: str = Field(..., min_length=1, max_length=128)
    mode: RunModeType
    completion: RunCompletionType
    started_at: datetime
    ended_at: datetime
    elapsed_ms: int = Field(..., gt=0)

    target_distance_km: float | None = Field(default=None, gt=0)
    target_duration_sec: int | None = Field(default=None, gt=0)

    distance_m: float | None = Field(default=None, ge=0)
    avg_pace_sec_per_km: int | None = Field(default=None, gt=0)
    cadence_spm: int | None = Field(default=None, gt=0)
    step_count: int | None = Field(default=None, ge=0)
    target_pace_keep_ratio_pct: float | None = Field(default=None, ge=0, le=100)

    pace_status: MetricStatusType = MetricStatusType.valid
    cadence_status: MetricStatusType = MetricStatusType.no_data
    music_track_id: str | None = None

    splits: List[RunSplitPayload] = Field(default_factory=list)
    gps_gaps: List[GpsGapPayload] = Field(default_factory=list)
    reflection: RunReflectionPayload | None = None
    # 스마트 인솔이 연결되어 유효한 데이터를 얻은 세션에만 전달 (미연결 시 None)
    posture_report: PostureReportPayload | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_frontend_nested_run_record(cls, data: dict) -> dict:
        """
        프론트엔드 src/features/running/types.ts 의 RunRecord 객체
        ({ recordId, sessionId, mode, startedAt, endedAt, goal, musicTrackId, result, reflection, sensorReport })를
        그대로 POST /api/v1/runs 바디에 넘겨도 자동 매핑되도록 지원.
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)
        # recordId 또는 sessionId를 client_session_id로 매핑
        if "client_session_id" not in out and "clientSessionId" not in out:
            out["client_session_id"] = out.get("recordId") or out.get("sessionId")
        # 중첩된 goal: { targetDistanceKm, targetDurationSec } 펼치기
        goal = out.get("goal")
        if isinstance(goal, dict):
            out.setdefault("target_distance_km", goal.get("targetDistanceKm") or goal.get("target_distance_km"))
            out.setdefault("target_duration_sec", goal.get("targetDurationSec") or goal.get("target_duration_sec"))
        # 중첩된 result: { elapsedMs, distanceM, avgPaceSecPerKm, splits, completion, gpsGaps } 펼치기
        result = out.get("result")
        if isinstance(result, dict):
            out.setdefault("elapsed_ms", result.get("elapsedMs") or result.get("elapsed_ms"))
            out.setdefault("distance_m", result.get("distanceM") if "distanceM" in result else result.get("distance_m"))
            out.setdefault(
                "avg_pace_sec_per_km",
                result.get("avgPaceSecPerKm") if "avgPaceSecPerKm" in result else result.get("avg_pace_sec_per_km"),
            )
            out.setdefault("completion", result.get("completion"))
            if "splits" in result and "splits" not in out:
                out["splits"] = result["splits"]
            if "gpsGaps" in result and "gps_gaps" not in out:
                out["gps_gaps"] = result["gpsGaps"]
        # sensorReport가 null로 오면 posture_report = None과 동일 취급
        if "sensorReport" in out and "posture_report" not in out:
            out["posture_report"] = out.get("sensorReport")
        return out

    @model_validator(mode="after")
    def enforce_time_mode_and_null_rules(self) -> "RunCreateRequest":
        if self.mode == RunModeType.time:
            self.completion = RunCompletionType.time
            self.distance_m = None
            self.avg_pace_sec_per_km = None
            self.target_distance_km = None
            self.target_duration_sec = None
            self.splits = []
            self.pace_status = MetricStatusType.no_data
        elif self.distance_m is None or self.distance_m <= 0:
            self.avg_pace_sec_per_km = None
            if self.pace_status == MetricStatusType.valid:
                self.pace_status = MetricStatusType.insufficient_data
        return self


class RunSummaryItemResponse(BaseModel):
    run_id: UUID
    client_session_id: str
    mode: RunModeType
    completion: RunCompletionType
    started_at: datetime
    ended_at: datetime
    elapsed_ms: int
    distance_m: float | None
    avg_pace_sec_per_km: int | None
    pace_status: MetricStatusType
    has_posture_report: bool


class RunDetailResponse(RunSummaryItemResponse):
    target_distance_km: float | None
    target_duration_sec: int | None
    target_pace_sec_per_km: int | None
    cadence_spm: int | None
    cadence_status: MetricStatusType
    step_count: int | None
    target_pace_keep_ratio_pct: float | None
    music_track_id: str | None
    splits: List[RunSplitPayload]
    gps_gaps: List[GpsGapPayload]
    reflection: RunReflectionPayload | None
    posture_report: PostureReportPayload | None
```

```python
# app/schemas/home.py
from datetime import datetime
from typing import List
from uuid import UUID
from pydantic import BaseModel
from app.schemas.common import MetricStatusType, RunCompletionType


class WeeklyActivitySummary(BaseModel):
    # 월요일(0) ~ 일요일(6) 달린 날 표시 배열
    run_days: List[bool]
    run_count: int
    # TIME 전용 러닝만 있으면 distance_m이 없으므로 0이 아닌 None 또는 유효 GPS 거리 합계만 반환
    total_gps_distance_m: float | None
    total_elapsed_ms: int


class LastRunBrief(BaseModel):
    run_id: UUID
    started_at: datetime
    completion: RunCompletionType
    distance_m: float | None
    elapsed_ms: int
    avg_pace_sec_per_km: int | None


class RecommendedGoalView(BaseModel):
    distance_km: float
    target_duration_sec: int
    target_pace_sec_per_km: int
    basis_type: str  # "recent_runs" | "baseline" | "default_starter"
    basis_description: str


class HomeSummaryResponse(BaseModel):
    weekly_activity: WeeklyActivitySummary
    last_run: LastRunBrief | None
    recommended_goal: RecommendedGoalView
    should_prompt_baseline: bool
    baseline_status: MetricStatusType
```

```python
# app/schemas/growth.py
from datetime import date
from typing import Dict, List
from pydantic import BaseModel
from app.schemas.common import GrowthPeriodType, MetricStatusType


class RunningPeriodBucket(BaseModel):
    period_start: date
    period_end: date
    run_count: int
    goal_completed_count: int
    # GPS 러닝이 없는 기간은 0으로 채우지 않고 None 반환
    total_distance_m: float | None
    total_elapsed_ms: int | None
    avg_pace_sec_per_km: int | None
    pace_status: MetricStatusType
    difficulty_counts: Dict[str, int]


class RunningGrowthResponse(BaseModel):
    period: GrowthPeriodType
    status: MetricStatusType
    buckets: List[RunningPeriodBucket]


class PosturePeriodBucket(BaseModel):
    period_start: date
    period_end: date
    valid_session_count: int
    single_foot_session_count: int
    status: MetricStatusType
    avg_ground_contact_left_ms: int | None
    avg_ground_contact_right_ms: int | None
    avg_left_load_ratio_pct: float | None
    avg_right_load_ratio_pct: float | None
    dominant_feedback: List[str]


class PostureGrowthResponse(BaseModel):
    period: GrowthPeriodType
    # 인솔 미구매·미연결 또는 유효 세션 0건일 때 "no_data" / "insufficient_data" 반환 (점수 추정 금지)
    overall_status: MetricStatusType
    buckets: List[PosturePeriodBucket]
```

### 4-8. 핵심 도메인 서비스 (`app/services/run_service.py`)

```python
import json
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.errors import AppError
from app.schemas.common import MetricStatusType
from app.schemas.run import (
    GpsGapPayload,
    MusicPresetResponse,
    PostureReportPayload,
    RunCreateRequest,
    RunDetailResponse,
    RunReflectionPayload,
    RunSplitPayload,
    RunSummaryItemResponse,
    TargetValidateRequest,
    TargetValidateResponse,
)

# 프론트엔드 목표 페이스 정책(4:00/km = 240초 ~ 10:00/km = 600초)과 동일한 기준
MIN_REALISTIC_PACE_SEC_PER_KM = 240
MAX_REALISTIC_PACE_SEC_PER_KM = 600


class RunService:
    @staticmethod
    def validate_target(payload: TargetValidateRequest) -> TargetValidateResponse:
        pace_sec = round(payload.target_duration_sec / payload.target_distance_km)
        if pace_sec < MIN_REALISTIC_PACE_SEC_PER_KM:
            return TargetValidateResponse(
                target_distance_km=payload.target_distance_km,
                target_duration_sec=payload.target_duration_sec,
                target_pace_sec_per_km=pace_sec,
                is_realistic=False,
                warning_code="PACE_TOO_FAST",
                warning_message="목표 페이스가 4:00/km보다 빠릅니다. 무리 없는 페이스로 조정해 보세요.",
            )
        if pace_sec > MAX_REALISTIC_PACE_SEC_PER_KM:
            return TargetValidateResponse(
                target_distance_km=payload.target_distance_km,
                target_duration_sec=payload.target_duration_sec,
                target_pace_sec_per_km=pace_sec,
                is_realistic=False,
                warning_code="PACE_TOO_SLOW",
                warning_message="목표 페이스가 10:00/km보다 느립니다. 목표 시간을 확인해 주세요.",
            )
        return TargetValidateResponse(
            target_distance_km=payload.target_distance_km,
            target_duration_sec=payload.target_duration_sec,
            target_pace_sec_per_km=pace_sec,
            is_realistic=True,
            warning_code=None,
            warning_message=None,
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
```

### 4-9. 라우터 및 앱 진입점 (`app/routers/*.py`, `app/main.py`)

```python
# app/routers/health.py
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db

router = APIRouter(tags=["System"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        return {"status": "degraded", "database": "unreachable"}
```

```python
# app/routers/runs.py
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
```

```python
# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.routers import health, runs

settings = get_settings()

app = FastAPI(
    title="Pacebeat API",
    version="1.0.0",
    description="Pacebeat 러닝 & 선택형 스마트 인솔 자세 리포트 백엔드 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(health.router)
app.include_router(runs.router)
# users.router, devices.router, home.router, growth.router 동일 방식으로 등록
```

---

## 5단계. 로컬 실행 방법 및 Koyeb 배포 가이드

### 5-1. 새 프로젝트 폴더에서 로컬 실행 방법

```bash
# 1. 새 백엔드 폴더 생성 및 이동
mkdir C:\react\pacebeat-backend
cd C:\react\pacebeat-backend

# 2. 가상환경 생성 및 활성화 (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. 패키지 설치
pip install -r requirements.txt

# 4. 환경변수 파일 생성 (.env.example 복사 후 Supabase 값 입력)
Copy-Item .env.example .env

# 5. 로컬 개발 서버 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Swagger UI 확인**: `http://localhost:8000/docs`
- **헬스체크 확인**: `http://localhost:8000/health`

### 5-2. Koyeb 클라우드 배포 설정 가이드

1. **Supabase DB 연결 문자열 주의사항**
   - Koyeb 컨테이너(IPv4 기반)에서 Supabase PostgreSQL에 연결할 때는 **Direct Connection(IPv6 전용)** 대신 Supabase Dashboard → **Connect → Transaction Pooler (포트 `6543`, IPv4 지원)** 주소를 사용합니다.
   - 형식: `postgresql+asyncpg://postgres.<project_ref>:<password>@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres`
2. **Koyeb 서비스 생성 설정**
   - **Deployment method**: GitHub Repository 연결 → Builder로 **`Dockerfile`** 선택
   - **Environment Variables**:
     - `APP_ENV` = `production`
     - `PORT` = `8000` (Koyeb이 동적으로 주입하는 `$PORT`도 `Dockerfile`의 `${PORT:-8000}`이 자동 대응)
     - `CORS_ORIGINS` = `["https://your-frontend-domain.vercel.app","http://localhost:5173"]`
     - `SUPABASE_URL` = `https://<project_ref>.supabase.co`
     - `SUPABASE_KEY` = `<anon_or_service_role_key>`
     - `SUPABASE_JWT_SECRET` = `<Supabase Project Settings -> API -> JWT Secret>`
     - `DATABASE_URL` = `<Supabase Pooler postgresql+asyncpg URL>`
3. **Koyeb Health Check 설정**
   - **Protocol**: `HTTP`
   - **Port**: `8000` (또는 동적 포트)
   - **Path**: `/health`
   - **Grace period**: `15s`, **Interval**: `30s`

---

## 부록. 나머지 4개 탭 라우터 전체 구현 코드 (`users.py`, `devices.py`, `home.py`, `growth.py`)

### A-1. `app/routers/users.py` (마이 - 프로필, 기초 측정, 안내 설정, 데이터 내보내기/삭제)

```python
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import AuthenticatedUser, get_current_user
from app.schemas.common import MetricStatusType
from app.schemas.user import (
    BaselineResponse,
    BaselineUpsertRequest,
    ConsentPayload,
    GuidanceSettingsPayload,
    UserProfileResponse,
    UserProfileUpdateRequest,
)

router = APIRouter(prefix="/api/v1/users/me", tags=["My - User & Baseline"])


async def _ensure_profile_row(db: AsyncSession, user_id: str) -> dict:
    row = (
        await db.execute(
            text("SELECT * FROM public.user_profiles WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
    ).first()
    if row:
        return dict(row._mapping)

    created = (
        await db.execute(
            text("INSERT INTO public.user_profiles (user_id) VALUES (:user_id) RETURNING *"),
            {"user_id": user_id},
        )
    ).first()
    await db.commit()
    return dict(created._mapping)


def _to_profile_response(m: dict) -> UserProfileResponse:
    return UserProfileResponse(
        user_id=m["user_id"],
        nickname=m["nickname"],
        birth_year=m["birth_year"],
        gender=m["gender"],
        height_cm=float(m["height_cm"]) if m["height_cm"] is not None else None,
        weight_kg=float(m["weight_kg"]) if m["weight_kg"] is not None else None,
        running_experience=m["running_experience"],
        consent=ConsentPayload(
            age_over_14=m["consent_age_over_14"],
            terms_of_service=m["consent_terms_of_service"],
            privacy_policy=m["consent_privacy_policy"],
            location_terms=m["consent_location_terms"],
            marketing=m["consent_marketing"],
            policy_version=m["consent_policy_version"],
            consented_at=m["consented_at"],
        ),
        guidance=GuidanceSettingsPayload(
            voice_guidance_enabled=m["voice_guidance_enabled"],
            vibration_guidance_enabled=m["vibration_guidance_enabled"],
            guidance_frequency_km=float(m["guidance_frequency_km"]),
            vibration_intensity=m["vibration_intensity"],
        ),
        onboarding_completed_at=m["onboarding_completed_at"],
        profile_completed_at=m["profile_completed_at"],
    )


@router.get("", response_model=UserProfileResponse)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> UserProfileResponse:
    m = await _ensure_profile_row(db, str(user.user_id))
    return _to_profile_response(m)


@router.patch("", response_model=UserProfileResponse)
async def update_my_profile(
    payload: UserProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> UserProfileResponse:
    uid = str(user.user_id)
    current = await _ensure_profile_row(db, uid)
    fields = payload.model_dump(exclude_unset=True)

    consent = fields.pop("consent", None)
    if consent:
        current["consent_age_over_14"] = consent["age_over_14"]
        current["consent_terms_of_service"] = consent["terms_of_service"]
        current["consent_privacy_policy"] = consent["privacy_policy"]
        current["consent_location_terms"] = consent["location_terms"]
        current["consent_marketing"] = consent["marketing"]
        current["consent_policy_version"] = consent["policy_version"]
        current["consented_at"] = consent["consented_at"] or datetime.now(timezone.utc)

    for k, v in fields.items():
        current[k] = v.value if hasattr(v, "value") else v

    updated = (
        await db.execute(
            text(
                """
                UPDATE public.user_profiles
                SET nickname = :nickname,
                    birth_year = :birth_year,
                    gender = :gender,
                    height_cm = :height_cm,
                    weight_kg = :weight_kg,
                    running_experience = :running_experience,
                    consent_age_over_14 = :consent_age_over_14,
                    consent_terms_of_service = :consent_terms_of_service,
                    consent_privacy_policy = :consent_privacy_policy,
                    consent_location_terms = :consent_location_terms,
                    consent_marketing = :consent_marketing,
                    consent_policy_version = :consent_policy_version,
                    consented_at = :consented_at,
                    onboarding_completed_at = :onboarding_completed_at,
                    profile_completed_at = :profile_completed_at
                WHERE user_id = :user_id
                RETURNING *
                """
            ),
            current,
        )
    ).first()
    await db.commit()
    return _to_profile_response(dict(updated._mapping))


@router.get("/baseline", response_model=BaselineResponse)
async def get_my_baseline(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> BaselineResponse:
    row = (
        await db.execute(
            text("SELECT * FROM public.user_baselines WHERE user_id = :user_id"),
            {"user_id": str(user.user_id)},
        )
    ).first()
    if not row:
        return BaselineResponse(
            user_id=user.user_id,
            skipped=False,
            quality_status=MetricStatusType.no_data,
            baseline_pace_sec_per_km=None,
            cadence_spm=None,
            stride_length_cm=None,
            valid_duration_ms=None,
            distance_m=None,
            measured_at=None,
        )
    m = row._mapping
    return BaselineResponse(
        user_id=m["user_id"],
        skipped=m["skipped"],
        quality_status=m["quality_status"],
        baseline_pace_sec_per_km=m["baseline_pace_sec_per_km"],
        cadence_spm=m["cadence_spm"],
        stride_length_cm=float(m["stride_length_cm"]) if m["stride_length_cm"] is not None else None,
        valid_duration_ms=m["valid_duration_ms"],
        distance_m=float(m["distance_m"]) if m["distance_m"] is not None else None,
        measured_at=m["measured_at"],
    )


@router.put("/baseline", response_model=BaselineResponse)
async def upsert_my_baseline(
    payload: BaselineUpsertRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> BaselineResponse:
    row = (
        await db.execute(
            text(
                """
                INSERT INTO public.user_baselines (
                    user_id, skipped, quality_status, baseline_pace_sec_per_km,
                    cadence_spm, stride_length_cm, valid_duration_ms, distance_m, measured_at
                ) VALUES (
                    :user_id, :skipped, :quality_status, :baseline_pace_sec_per_km,
                    :cadence_spm, :stride_length_cm, :valid_duration_ms, :distance_m, :measured_at
                )
                ON CONFLICT (user_id) DO UPDATE SET
                    skipped = EXCLUDED.skipped,
                    quality_status = EXCLUDED.quality_status,
                    baseline_pace_sec_per_km = EXCLUDED.baseline_pace_sec_per_km,
                    cadence_spm = EXCLUDED.cadence_spm,
                    stride_length_cm = EXCLUDED.stride_length_cm,
                    valid_duration_ms = EXCLUDED.valid_duration_ms,
                    distance_m = EXCLUDED.distance_m,
                    measured_at = EXCLUDED.measured_at
                RETURNING *
                """
            ),
            {
                "user_id": str(user.user_id),
                "skipped": payload.skipped,
                "quality_status": payload.quality_status.value,
                "baseline_pace_sec_per_km": payload.baseline_pace_sec_per_km,
                "cadence_spm": payload.cadence_spm,
                "stride_length_cm": payload.stride_length_cm,
                "valid_duration_ms": payload.valid_duration_ms,
                "distance_m": payload.distance_m,
                "measured_at": payload.measured_at or datetime.now(timezone.utc),
            },
        )
    ).first()
    await db.commit()
    m = row._mapping
    return BaselineResponse(
        user_id=m["user_id"],
        skipped=m["skipped"],
        quality_status=m["quality_status"],
        baseline_pace_sec_per_km=m["baseline_pace_sec_per_km"],
        cadence_spm=m["cadence_spm"],
        stride_length_cm=float(m["stride_length_cm"]) if m["stride_length_cm"] is not None else None,
        valid_duration_ms=m["valid_duration_ms"],
        distance_m=float(m["distance_m"]) if m["distance_m"] is not None else None,
        measured_at=m["measured_at"],
    )


@router.patch("/guidance", response_model=GuidanceSettingsPayload)
async def update_my_guidance(
    payload: GuidanceSettingsPayload,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> GuidanceSettingsPayload:
    await _ensure_profile_row(db, str(user.user_id))
    await db.execute(
        text(
            """
            UPDATE public.user_profiles
            SET voice_guidance_enabled = :voice_guidance_enabled,
                vibration_guidance_enabled = :vibration_guidance_enabled,
                guidance_frequency_km = :guidance_frequency_km,
                vibration_intensity = :vibration_intensity
            WHERE user_id = :user_id
            """
        ),
        {
            "user_id": str(user.user_id),
            **payload.model_dump(),
        },
    )
    await db.commit()
    return payload


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account_data(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Response:
    uid = str(user.user_id)
    await db.execute(text("DELETE FROM public.run_sessions WHERE user_id = :uid"), {"uid": uid})
    await db.execute(text("DELETE FROM public.insole_devices WHERE user_id = :uid"), {"uid": uid})
    await db.execute(text("DELETE FROM public.user_baselines WHERE user_id = :uid"), {"uid": uid})
    await db.execute(text("DELETE FROM public.user_profiles WHERE user_id = :uid"), {"uid": uid})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

### A-2. `app/routers/devices.py` (마이 - 선택형 스마트 인솔 좌/우 기기 관리)

```python
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
```

### A-3. `app/routers/home.py` (홈 대시보드 통합 요약)

```python
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import AuthenticatedUser, get_current_user
from app.schemas.common import MetricStatusType
from app.schemas.home import (
    HomeSummaryResponse,
    LastRunBrief,
    RecommendedGoalView,
    WeeklyActivitySummary,
)

router = APIRouter(prefix="/api/v1/home", tags=["Home"])


@router.get("/summary", response_model=HomeSummaryResponse)
async def get_home_summary(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> HomeSummaryResponse:
    uid = str(user.user_id)
    now = datetime.now(timezone.utc)
    # 월요일(0) 기준 이번 주 시작 시각
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    week_rows = (
        await db.execute(
            text(
                """
                SELECT started_at, mode, distance_m, elapsed_ms
                FROM public.run_sessions
                WHERE user_id = :uid AND started_at >= :monday
                ORDER BY started_at DESC
                """
            ),
            {"uid": uid, "monday": monday},
        )
    ).fetchall()

    run_days = [False] * 7
    gps_distances: list[float] = []
    total_elapsed_ms = 0
    for r in week_rows:
        m = r._mapping
        weekday_idx = m["started_at"].weekday()
        run_days[weekday_idx] = True
        total_elapsed_ms += int(m["elapsed_ms"])
        if m["mode"] == "gps" and m["distance_m"] is not None:
            gps_distances.append(float(m["distance_m"]))

    last_row = (
        await db.execute(
            text(
                """
                SELECT id, started_at, completion, distance_m, elapsed_ms, avg_pace_sec_per_km
                FROM public.run_sessions
                WHERE user_id = :uid
                ORDER BY started_at DESC
                LIMIT 1
                """
            ),
            {"uid": uid},
        )
    ).first()

    last_run = (
        LastRunBrief(
            run_id=last_row._mapping["id"],
            started_at=last_row._mapping["started_at"],
            completion=last_row._mapping["completion"],
            distance_m=float(last_row._mapping["distance_m"])
            if last_row._mapping["distance_m"] is not None
            else None,
            elapsed_ms=last_row._mapping["elapsed_ms"],
            avg_pace_sec_per_km=last_row._mapping["avg_pace_sec_per_km"],
        )
        if last_row
        else None
    )

    baseline_row = (
        await db.execute(
            text("SELECT quality_status, baseline_pace_sec_per_km FROM public.user_baselines WHERE user_id = :uid"),
            {"uid": uid},
        )
    ).first()

    baseline_status = (
        MetricStatusType(baseline_row._mapping["quality_status"])
        if baseline_row
        else MetricStatusType.no_data
    )
    baseline_pace = baseline_row._mapping["baseline_pace_sec_per_km"] if baseline_row else None

    if baseline_status == MetricStatusType.valid and baseline_pace:
        pace = int(baseline_pace)
        recommended = RecommendedGoalView(
            distance_km=3.0,
            target_duration_sec=pace * 3,
            target_pace_sec_per_km=pace,
            basis_type="baseline",
            basis_description="기초 측정 기준 페이스를 바탕으로 설정된 목표입니다.",
        )
    else:
        # 기준이 없을 때 프론트엔드 기본 목표(3km, 21:00 = 1260초, 7:00/km = 420초)와 일치
        recommended = RecommendedGoalView(
            distance_km=3.0,
            target_duration_sec=1260,
            target_pace_sec_per_km=420,
            basis_type="default_starter",
            basis_description="누구나 부담 없이 시작할 수 있는 기본 3.0 km 목표입니다.",
        )

    return HomeSummaryResponse(
        weekly_activity=WeeklyActivitySummary(
            run_days=run_days,
            run_count=len(week_rows),
            total_gps_distance_m=sum(gps_distances) if gps_distances else None,
            total_elapsed_ms=total_elapsed_ms,
        ),
        last_run=last_run,
        recommended_goal=recommended,
        should_prompt_baseline=(baseline_status != MetricStatusType.valid),
        baseline_status=baseline_status,
    )
```

### A-4. `app/routers/growth.py` (성장 - 주간/월간 러닝 추이 및 자세 리포트 비교)

```python
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import AuthenticatedUser, get_current_user
from app.schemas.common import GrowthPeriodType, MetricStatusType
from app.schemas.growth import (
    PostureGrowthResponse,
    PosturePeriodBucket,
    RunningGrowthResponse,
    RunningPeriodBucket,
)

router = APIRouter(prefix="/api/v1/growth", tags=["Growth"])


@router.get("/running", response_model=RunningGrowthResponse)
async def get_running_growth(
    period: GrowthPeriodType = Query(default=GrowthPeriodType.weekly),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> RunningGrowthResponse:
    days = 7 if period == GrowthPeriodType.weekly else 30
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=days)

    rows = (
        await db.execute(
            text(
                """
                SELECT mode, completion, distance_m, elapsed_ms, avg_pace_sec_per_km, reflection_difficulty
                FROM public.run_sessions
                WHERE user_id = :uid AND started_at >= :start_dt
                """
            ),
            {"uid": str(user.user_id), "start_dt": start_dt},
        )
    ).fetchall()

    if not rows:
        return RunningGrowthResponse(period=period, status=MetricStatusType.no_data, buckets=[])

    gps_distances = [float(r._mapping["distance_m"]) for r in rows if r._mapping["mode"] == "gps" and r._mapping["distance_m"] is not None]
    gps_paces = [int(r._mapping["avg_pace_sec_per_km"]) for r in rows if r._mapping["mode"] == "gps" and r._mapping["avg_pace_sec_per_km"] is not None]
    diff_counts = {"easy": 0, "moderate": 0, "hard": 0}
    for r in rows:
        d = r._mapping["reflection_difficulty"]
        if d in diff_counts:
            diff_counts[d] += 1

    bucket = RunningPeriodBucket(
        period_start=start_dt.date(),
        period_end=now.date(),
        run_count=len(rows),
        goal_completed_count=sum(1 for r in rows if r._mapping["completion"] == "goal"),
        total_distance_m=sum(gps_distances) if gps_distances else None,
        total_elapsed_ms=sum(int(r._mapping["elapsed_ms"]) for r in rows),
        avg_pace_sec_per_km=round(sum(gps_paces) / len(gps_paces)) if gps_paces else None,
        pace_status=MetricStatusType.valid if gps_paces else MetricStatusType.no_data,
        difficulty_counts=diff_counts,
    )
    return RunningGrowthResponse(period=period, status=MetricStatusType.valid, buckets=[bucket])


@router.get("/posture", response_model=PostureGrowthResponse)
async def get_posture_growth(
    period: GrowthPeriodType = Query(default=GrowthPeriodType.weekly),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
) -> PostureGrowthResponse:
    days = 7 if period == GrowthPeriodType.weekly else 30
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=days)

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
            {"uid": str(user.user_id), "start_dt": start_dt},
        )
    ).fetchall()

    # 인솔 미구매·미연결 사용자는 자세 데이터를 추정하지 않고 명시적 no_data 반환
    if not rows:
        return PostureGrowthResponse(period=period, overall_status=MetricStatusType.no_data, buckets=[])

    valid_rows = [r._mapping for r in rows if r._mapping["posture_status"] == "valid"]
    single_rows = [r._mapping for r in rows if r._mapping["posture_status"] == "single_foot"]

    gct_l = [int(m["ground_contact_time_left_ms"]) for m in rows if m["ground_contact_time_left_ms"] is not None]
    gct_r = [int(m["ground_contact_time_right_ms"]) for m in rows if m["ground_contact_time_right_ms"] is not None]
    load_l = [float(m["left_load_ratio_pct"]) for m in valid_rows if m["left_load_ratio_pct"] is not None]
    load_r = [float(m["right_load_ratio_pct"]) for m in valid_rows if m["right_load_ratio_pct"] is not None]

    overall_status = (
        MetricStatusType.valid
        if valid_rows
        else (MetricStatusType.single_foot if single_rows else MetricStatusType.insufficient_data)
    )

    bucket = PosturePeriodBucket(
        period_start=start_dt.date(),
        period_end=now.date(),
        valid_session_count=len(valid_rows),
        single_foot_session_count=len(single_rows),
        status=overall_status,
        avg_ground_contact_left_ms=round(sum(gct_l) / len(gct_l)) if gct_l else None,
        avg_ground_contact_right_ms=round(sum(gct_r) / len(gct_r)) if gct_r else None,
        avg_left_load_ratio_pct=round(sum(load_l) / len(load_l), 2) if load_l else None,
        avg_right_load_ratio_pct=round(sum(load_r) / len(load_r), 2) if load_r else None,
        dominant_feedback=[],
    )
    return PostureGrowthResponse(period=period, overall_status=overall_status, buckets=[bucket])
```

---

## 부록 B. 프론트엔드(`pacebeat-frontend`) ↔ 백엔드 데이터 타입 & 더미데이터 1:1 매핑 검증표

현재 프론트엔드 코드베이스에 구현된 TypeScript 타입 및 고정(더미) 데이터와 백엔드 DB/Pydantic 스키마의 일치 내역입니다.

| 도메인 / 프론트엔드 파일 | 프론트엔드 타입 / 더미데이터 값 | 백엔드 스키마 / DB 매핑 | 호환 방식 |
|---|---|---|---|
| **케이스 & 시각 변환**<br>전체 공통 | `camelCase` 프로퍼티 & `number` (Unix epoch ms, `Date.now()`) | `CamelModel` (`alias_generator=to_camel`, `populate_by_name=True`) + `EpochDatetime` | 요청 시 `camelCase`/`snake_case` 및 `epoch ms`/`ISO 문자열` 모두 허용 |
| **온보딩 경험 수준**<br>`src/types/onboarding.ts` | `ExperienceLevel = 'beginner' \| 'occasional' \| 'regular'`<br>`WeeklyRuns = '1' \| '2' \| '3+'` | `running_experience_type ENUM ('beginner', 'occasional', 'regular')`<br>`weekly_runs_type ENUM ('1', '2', '3+')` | **1:1 완전 일치** |
| **프로필 & 약관 동의**<br>`src/features/profile/types.ts` | `ProfileData`: `nickname`(2~10자), `birthYear`, `gender`(`'female'\|'male'\|null`), `heightCm`, `weightKg`<br>`ConsentData`: `ageOver14`, `termsOfService`, `privacyPolicy`, `locationTerms`, `marketing`, `policyVersion`, `consentedAt` | `user_profiles` 테이블 및 `UserProfileResponse` / `ConsentPayload` | 미입력값 `0` 대신 `null` 허용까지 **1:1 완전 일치** |
| **기초 측정 기준 페이스**<br>`src/features/measurement/baseline.ts` | `BASELINE_MIN_VALID_MS = 120_000`<br>`validMs < 120_000`이면 `avgPaceSecPerKm = null` (`sec/km` 정수) | `user_baselines` & `BaselineUpsertRequest.enforce_null_when_insufficient` | `valid_duration_ms < 120_000`일 때 `insufficient_data` + `baseline_pace_sec_per_km = null` **1:1 완전 일치** |
| **음악 프리셋 (더미 4곡)**<br>`src/features/running/music.ts` | `MUSIC_TRACKS`:<br>1. `morning-stride` (`Morning Stride`, `158` BPM)<br>2. `city-loop` (`City Loop`, `156` BPM)<br>3. `easy-tempo` (`Easy Tempo`, `160` BPM)<br>4. `night-pace` (`Night Pace`, `150` BPM) | `music_presets` 초기 Seed SQL & `MusicPresetResponse` (`id`, `title`, `bpm`) | 4곡 ID·제목·BPM **1:1 완전 일치** |
| **러닝 기록 & 결과**<br>`src/features/running/types.ts` | `RunRecord` (`recordId`, `sessionId`, `mode`: `'gps'\|'time'`, `startedAt`, `endedAt`, `goal`: `{targetDistanceKm, targetDurationSec}`, `musicTrackId`, `result`: `{elapsedMs, distanceM, avgPaceSecPerKm, splits, completion, gpsGaps}`, `reflection`, `sensorReport: null`) | `RunCreateRequest.accept_frontend_nested_run_record` | 프론트엔드 `RunRecord` JSON을 변환 없이 그대로 `POST /api/v1/runs`에 전송해도 자동 매핑 및 멱등(`recordId` → `client_session_id`) 저장 |
| **러닝 회고 (리포트)**<br>`src/features/running/types.ts` | `ReflectionDifficulty = 'easy' \| 'moderate' \| 'hard'`<br>`ReflectionReason = 'breath' \| 'legs' \| 'boredom' \| 'time'`<br>`memo`: 최대 100자 | `reflection_difficulty_type ENUM ('easy', 'moderate', 'hard')`<br>`ReflectionReasonType` (`breath`, `legs`, `boredom`, `time`)<br>`VARCHAR(100)` | `'moderate'`와 `'boredom'` 철자까지 **1:1 완전 일치** |
| **홈 기본 목표 & 주간 요일**<br>`src/features/home/homeView.ts`<br>`src/features/home/homeRecords.ts` | 기본 목표 `3.0 km`, `1260`초(`21:00`), `420 sec/km`(`7:00 /km`)<br>월요일(0)~일요일(6) `runDays: boolean[7]` | `GET /api/v1/home/summary` (`distance_km=3.0`, `target_duration_sec=1260`, `target_pace_sec_per_km=420`, `run_days: bool[7]`) | **1:1 완전 일치** |
