from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class CreateJobRequest(BaseModel):
    url: HttpUrl
    count: int = Field(default=3, ge=1, le=8)
    min_score: int = Field(default=75, ge=0, le=100)
    min_duration: int = Field(default=45, ge=15, le=180)
    max_duration: int = Field(default=90, ge=20, le=240)
    quality: str = Field(default="alta", pattern="^(tiktok|alta|4k)$")
    ai_mode: str = Field(default="auto", pattern="^(auto|off|required)$")
    preview_only: bool = False


class JobResponse(BaseModel):
    id: str
    user_id: str
    url: str
    status: str
    stage: str
    progress: int
    request: dict
    result: dict
    error: str
    log: list[str]
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
