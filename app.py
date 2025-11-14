"""FastAPI service that proxies attendance data from a BioStar2 server."""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Iterable, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, BaseSettings, Field, validator

from biostar2_client import BioStar2Client, BioStar2Error


class Settings(BaseSettings):
    """Application configuration sourced from environment variables."""

    biostar_base_url: str = Field(..., env="BIOSTAR2_BASE_URL")
    biostar_username: str = Field(..., env="BIOSTAR2_USERNAME")
    biostar_password: str = Field(..., env="BIOSTAR2_PASSWORD")
    verify_ssl: bool = Field(True, env="BIOSTAR2_VERIFY_SSL")

    class Config:
        case_sensitive = False
        env_file = os.environ.get("BIOSTAR2_ENV_FILE", None)


def get_settings() -> Settings:
    return Settings()


def create_client(settings: Settings = Depends(get_settings)) -> BioStar2Client:
    return BioStar2Client(
        base_url=settings.biostar_base_url,
        username=settings.biostar_username,
        password=settings.biostar_password,
        verify_ssl=settings.verify_ssl,
    )


app = FastAPI(title="BioStar2 Attendance Gateway", version="0.1.0")


class AttendanceRecord(BaseModel):
    """Representation of an attendance event."""

    user_id: str
    event_type: Optional[str] = None
    datetime: datetime
    device_id: Optional[str] = None
    raw: dict

    @validator("datetime", pre=True)
    def _parse_datetime(cls, value):  # type: ignore[override]
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @classmethod
    def from_api(cls, payload: dict) -> "AttendanceRecord":
        return cls(
            user_id=str(payload.get("user_id")),
            event_type=payload.get("event_type", payload.get("event_type_id")),
            datetime=payload.get("datetime"),
            device_id=payload.get("device_id"),
            raw=payload,
        )


class LeaveRecord(BaseModel):
    user_id: str
    leave_type: Optional[str] = None
    start_datetime: datetime
    end_datetime: datetime
    approved: Optional[bool] = None
    raw: dict

    @validator("start_datetime", "end_datetime", pre=True)
    def _parse_datetime(cls, value):  # type: ignore[override]
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @classmethod
    def from_api(cls, payload: dict) -> "LeaveRecord":
        return cls(
            user_id=str(payload.get("user_id")),
            leave_type=payload.get("leave_type", payload.get("leave_type_id")),
            start_datetime=payload.get("start_datetime"),
            end_datetime=payload.get("end_datetime"),
            approved=payload.get("approved", payload.get("approval_status") == "approved"),
            raw=payload,
        )


class AttendanceResponse(BaseModel):
    total: int
    records: List[AttendanceRecord]


class LeaveResponse(BaseModel):
    total: int
    records: List[LeaveRecord]


def _split_user_ids(value: Optional[str]) -> Optional[Iterable[str]]:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


@app.get("/attendance", response_model=AttendanceResponse)
def get_attendance(
    start: datetime = Query(..., description="Start datetime (ISO 8601)."),
    end: datetime = Query(..., description="End datetime (ISO 8601)."),
    user_ids: Optional[str] = Query(None, description="Comma separated list of BioStar2 user IDs."),
    client: BioStar2Client = Depends(create_client),
) -> AttendanceResponse:
    try:
        records = client.get_attendance_events(
            start_datetime=start.isoformat(),
            end_datetime=end.isoformat(),
            user_ids=_split_user_ids(user_ids),
        )
    except BioStar2Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AttendanceResponse(
        total=len(records),
        records=[AttendanceRecord.from_api(item) for item in records],
    )


@app.get("/leaves", response_model=LeaveResponse)
def get_leaves(
    start: date = Query(..., description="Start date (YYYY-MM-DD)."),
    end: date = Query(..., description="End date (YYYY-MM-DD)."),
    user_ids: Optional[str] = Query(None, description="Comma separated list of BioStar2 user IDs."),
    client: BioStar2Client = Depends(create_client),
) -> LeaveResponse:
    try:
        records = client.get_leaves(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            user_ids=_split_user_ids(user_ids),
        )
    except BioStar2Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return LeaveResponse(
        total=len(records),
        records=[LeaveRecord.from_api(item) for item in records],
    )
