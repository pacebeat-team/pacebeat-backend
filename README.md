# Pacebeat Backend API (FastAPI + Supabase + Koyeb)

**Pacebeat** 프론트엔드(5탭 정보구조: 홈 / 러닝 / 기록 / 성장 / 마이)와 연동되는 백엔드 API 서버입니다.

---

## 1. 핵심 도메인 원칙 및 아키텍처 기준 (ADR 준수)

1. **스마트폰 단독 기본 서비스 (ADR-001)**
   - 스마트 인솔 구매·연결을 시작 조건으로 요구하지 않으며, 스마트폰만으로 온보딩·기초 측정·목표 설정·러닝·기록·성장 기능을 모두 사용할 수 있습니다.
2. **러닝 리포트와 자세 리포트의 엄격한 분리**
   - 모든 러닝 세션(`run_sessions`)은 **러닝 리포트**(거리, 시간, GPS 페이스, 지원 기기 한정 케이던스, 구간 기록 `run_splits`, 목표 달성도, 리포트/회고)를 가집니다.
   - **자세 리포트**(`run_posture_reports`)는 스마트 인솔이 연결되어 유효한 데이터를 수집한 세션에만 선택적(`0..1`)으로 생성됩니다.
   - 인솔 미구매·미연결 시 자세 점수를 추정하지 않으며, 한쪽 인솔만 유효한 경우 양발 비교 지표를 `null`로 비우고 `posture_status = 'single_foot'`으로 응답합니다.
3. **결측치 및 예외 상태 표현 원칙 (ADR-003, ADR-004)**
   - 모든 페이스(Pace)는 내부 및 DB에 **`sec/km` 정수**(예: `5'30"/km` → `330`)로 저장합니다.
   - 측정 실패, 걸음 수 없음, GPS 불량, TIME 모드(거리 미측정), 데이터 부족, 휴식일 등은 **`0`이 아닌 `null`**과 명시적 상태 코드(`valid`, `insufficient_data`, `no_data`, `gps_poor`, `single_foot`, `sensor_disconnected`)로 구분해 응답합니다.
4. **오프라인 및 네트워크 재시도 멱등성(Idempotency)**
   - 러닝 종료 후 저장 재시도 시 중복 레코드가 생성되지 않도록 `(user_id, client_session_id)` 유니크 제약과 **Upsert(멱등 저장)**를 지원합니다.

---

## 2. 프로젝트 디렉토리 구조

```text
pacebeat-backend/
├── app/
│   ├── main.py                     # FastAPI 앱 진입점, CORS, 예외 핸들러, 라우터 등록
│   ├── core/                       # 환경변수(config), DB(database), 에러(errors), JWT 인증(security)
│   ├── routers/                    # 5탭 API 엔드포인트 (health, users, devices, home, runs, growth)
│   ├── schemas/                    # Pydantic v2 요청/응답 스키마 (camelCase/snake_case 양방향 호환)
│   ├── services/                   # 비즈니스 도메인 로직 계층
│   └── repositories/               # SQLAlchemy 2.0 Async DB 접근 계층
├── sql/
│   └── 001_init_schema_and_rls.sql # Supabase SQL Editor 실행용 DDL & RLS 스크립트
├── tests/
│   └── test_domain_rules.py        # 도메인 규칙 단위 테스트
├── .env.example
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 3. API 엔드포인트 요약

| 분류 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| **System** | `GET` | `/health` | 불필요 | Koyeb 컨테이너 헬스체크 및 DB 연결 상태 확인 |
| **My (프로필)** | `GET` | `/api/v1/users/me` | Bearer JWT | 내 프로필, 러닝 경험, 약관 동의, 안내 설정 통합 조회 |
| **My (프로필)** | `PATCH` | `/api/v1/users/me` | Bearer JWT | 프로필, 러닝 경험, 약관 동의 수정 |
| **My (기초측정)** | `GET` | `/api/v1/users/me/baseline` | Bearer JWT | 개인 기준(기준 페이스 `sec/km`, 케이던스, 보폭, 측정 품질 상태) 조회 |
| **My (기초측정)** | `PUT` | `/api/v1/users/me/baseline` | Bearer JWT | 기초 측정 결과 저장·재설정 (`skipped=true` 및 120초 미만 `insufficient_data` 지원) |
| **My (안내설정)** | `PATCH` | `/api/v1/users/me/guidance` | Bearer JWT | 음성·진동 안내 설정 변경 |
| **My (데이터)** | `POST` | `/api/v1/users/me/data-export` | Bearer JWT | 개인 프로필·측정·러닝·자세 데이터 전체 JSON 내보내기 |
| **My (데이터)** | `DELETE` | `/api/v1/users/me` | Bearer JWT | 계정 및 연관 러닝 데이터 전체 삭제 요청 |
| **My (인솔)** | `GET` | `/api/v1/devices/insoles` | Bearer JWT | 좌/우 스마트 인솔 등록 현황, 배터리, 연결·보정·신호 품질 상태 조회 |
| **My (인솔)** | `POST` | `/api/v1/devices/insoles` | Bearer JWT | 좌(`left`) 또는 우(`right`) 스마트 인솔 기기 등록(페어링) |
| **My (인솔)** | `PATCH` | `/api/v1/devices/insoles/{side}` | Bearer JWT | 좌/우 인솔 연결 상태, 배터리, 펌웨어, 착용 보정, 신호 품질 업데이트 |
| **My (인솔)** | `DELETE` | `/api/v1/devices/insoles/{side}` | Bearer JWT | 좌/우 스마트 인솔 연결 해제 및 기기 등록 삭제 |
| **Home** | `GET` | `/api/v1/home/summary` | Bearer JWT | 홈 대시보드 통합 조회 (이번 주 달린 요일·요약, 지난 러닝, 다음 추천 목표·페이스) |
| **Running** | `POST` | `/api/v1/runs/targets/validate` | Bearer JWT | 목표 거리·시간 입력 시 목표 페이스(`sec/km`) 계산 및 비현실적 목표 경고 검증 |
| **Running** | `GET` | `/api/v1/music/presets` | Bearer JWT | 러닝 음악·박자(BPM) 프리셋 목록 조회 |
| **Running** | `POST` | `/api/v1/runs` | Bearer JWT | 러닝 세션 멱등 저장 (`client_session_id` 기반, 구간 기록 및 조건부 자세 리포트 저장) |
| **Records** | `GET` | `/api/v1/runs` | Bearer JWT | 기간별(`from`, `to`) 러닝 기록 목록 조회 |
| **Records** | `GET` | `/api/v1/runs/{run_id}` | Bearer JWT | 개별 러닝 상세 조회 (`has_posture_report` 플래그, 러닝/구간/자세 리포트 반환) |
| **Records** | `PATCH` | `/api/v1/runs/{run_id}/reflection` | Bearer JWT | 러닝 리포트 회고(체감 난이도, 힘들었던 이유 배열, 100자 이내 메모) 저장·수정 |
| **Growth** | `GET` | `/api/v1/growth/running` | Bearer JWT | 주간/월간(`period=weekly\|monthly`) 러닝 성장 추이 조회 |
| **Growth** | `GET` | `/api/v1/growth/posture` | Bearer JWT | 주간/월간(`period=weekly\|monthly`) 자세 리포트 변화 비교 조회 |

---

## 4. 로컬 개발 환경 실행 방법

```powershell
# 1. 가상환경 생성 및 활성화 (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 의존성 패키지 설치
pip install -r requirements.txt

# 3. 환경변수 파일 생성 (.env.example 복사 후 Supabase 접속 정보 입력)
Copy-Item .env.example .env

# 4. 로컬 개발 서버 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Swagger UI**: `http://localhost:8000/docs`
- **Health Check**: `http://localhost:8000/health`
- **단위 테스트 실행**: `pytest`

---

## 5. Supabase & Koyeb 배포 설정

1. **Supabase DB 초기화**: Supabase Dashboard → SQL Editor에서 `sql/001_init_schema_and_rls.sql`을 실행합니다.
2. **Koyeb DB 연결**: Koyeb(IPv4)에서는 Supabase **Transaction Pooler (포트 `6543`)** URL(`postgresql+asyncpg://...`)을 `DATABASE_URL`에 설정합니다.
3. **Koyeb Health Check**: HTTP 경로 `/health` (포트 `8000`)로 설정합니다.
