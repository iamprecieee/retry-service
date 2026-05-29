from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from app.config import settings


class SuccessResponse[DataT](BaseModel):
    status: Literal["success"] = "success"
    message: str
    data: DataT | None = None


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    message: str


class RequestCreate(BaseModel):
    url: AnyHttpUrl
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    body: str | None = None
    max_retries: int = Field(default=settings.default_max_retries, ge=0)
    backoff_ms: int = Field(default=settings.default_backoff_ms, ge=100)


class RequestQueued(BaseModel):
    id: str
    status: str


class AttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    attempt_number: int
    attempted_at: datetime
    status_code: int | None
    error: str | None
    response_body: str | None
    wait_ms: int | None


class RequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    method: str
    body: str | None
    status: str
    attempt_count: int
    max_retries: int
    backoff_ms: int
    next_retry_at: float | None
    last_error: str | None
    result: str | None
    created_at: datetime
    updated_at: datetime
    attempts: list[AttemptResponse] = []


class RequestListData(BaseModel):
    requests: list[RequestResponse]
    count: int
