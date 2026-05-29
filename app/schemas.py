import json
from datetime import datetime
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.config import settings

METHODS_WITHOUT_BODY = {"GET", "DELETE", "HEAD"}
MAX_URL_LENGTH = 2048
MAX_BODY_SIZE_BYTES = 1_048_576  # 1MB


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

    @field_validator("url")
    @classmethod
    def validate_url_length(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if len(str(value)) > MAX_URL_LENGTH:
            raise ValueError(f"url must not exceed {MAX_URL_LENGTH} characters")
        return value

    @field_validator("body")
    @classmethod
    def validate_body_is_json(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if len(value.encode("utf-8")) > MAX_BODY_SIZE_BYTES:
            raise ValueError(
                f"body must not exceed {MAX_BODY_SIZE_BYTES // 1_048_576}MB"
            )
        try:
            json.loads(value)
        except json.JSONDecodeError:
            raise ValueError("body must be valid JSON")
        return value

    @model_validator(mode="after")
    def validate_body_allowed_for_method(self) -> "RequestCreate":
        if self.method in METHODS_WITHOUT_BODY and self.body is not None:
            raise ValueError(f"body is not allowed for {self.method} requests")
        return self


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
