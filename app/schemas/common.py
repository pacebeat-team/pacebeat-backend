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
