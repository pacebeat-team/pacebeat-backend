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
