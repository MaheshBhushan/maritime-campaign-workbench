"""API request and response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class VesselIn(BaseModel):
    key: str = Field(min_length=1, max_length=100, description="Client-side reference used by tasks")
    name: str = Field(min_length=1, max_length=200)
    vessel_class: str = Field(min_length=1, max_length=100)
    home_port: str = Field(default="", max_length=200)
    turnaround_hours: float = Field(default=0.0, ge=0, le=720)


class TaskIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=100)
    duration_hours: float = Field(gt=0, le=8760)
    vessel: str = Field(min_length=1, description="Key of a vessel in the same request")
    depends_on: list[str] = Field(default_factory=list)


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(default="", max_length=4000)
    start_time: datetime
    vessels: list[VesselIn] = Field(min_length=1)
    tasks: list[TaskIn] = Field(min_length=1)

    @field_validator("start_time")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("start_time must include a timezone offset")
        return v


class VesselOut(BaseModel):
    id: int
    name: str
    vessel_class: str
    home_port: str
    turnaround_hours: float


class TaskOut(BaseModel):
    id: int
    name: str
    kind: str
    duration_hours: float
    vessel_id: int
    depends_on: list[int]


class ScheduleOut(BaseModel):
    task_id: int
    vessel_id: int
    start: datetime
    end: datetime


class DocumentOut(BaseModel):
    id: str
    title: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    object_key: str
    tags: list[str]
    uploaded_at: datetime


class CampaignSummary(BaseModel):
    id: int
    name: str
    start_time: datetime
    synthetic: bool
    vessel_count: int
    task_count: int
    document_count: int


class CampaignOut(BaseModel):
    id: int
    name: str
    objective: str
    start_time: datetime
    synthetic: bool
    makespan_hours: float
    vessels: list[VesselOut]
    tasks: list[TaskOut]
    schedule: list[ScheduleOut]
    documents: list[DocumentOut]


class SparqlIn(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
