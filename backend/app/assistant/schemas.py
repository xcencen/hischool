"""Strict assistant requests and explicit public response projections."""

from datetime import UTC
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator


Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=100)]
Content = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
RequestKey = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64,
                                             pattern=r"^[A-Za-z0-9_-]+$")]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", check_fields=False)
    @classmethod
    def valid_text_encoding(cls, value):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise ValueError("Text must be valid UTF-8") from None
        return value


class ConversationCreate(StrictRequest):
    title: Title = "新会话"


class ConversationUpdate(StrictRequest):
    title: Title | None = None
    state: Literal["active", "archived"] | None = None

    @field_validator("title", "state")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("Fields cannot be null")
        return value

    @model_validator(mode="after")
    def non_empty(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class RunCreate(StrictRequest):
    content: Content
    request_key: RequestKey


class RunRetry(StrictRequest):
    request_key: RequestKey


def timestamp(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def run_response(run):
    """Never serialize ORM __dict__: source-session and lease fields are private."""
    return dict(id=run.public_id, conversation_id=getattr(run, "conversation_public_id", None),
        status=run.status, reason=run.reason, cancel_requested=bool(run.cancel_requested),
        model_calls=run.model_calls, tool_calls=run.tool_calls,
        cost_limit=str(run.cost_limit), reserved=str(run.reserved), spent=str(run.spent),
        budget_day=run.budget_day.isoformat(), created_at=timestamp(run.create_time),
        started_at=timestamp(run.started_at), finished_at=timestamp(run.finished_at),
        deadline_at=timestamp(run.deadline_at))


def alert_response(alert):
    return dict(id=alert.id, day=alert.day.isoformat(), scope=alert.scope, kind=alert.kind,
                amount=str(alert.amount), cap=str(alert.cap), acknowledged=bool(alert.acknowledged),
                created_at=timestamp(alert.create_time))
