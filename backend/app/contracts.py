"""Strict public input contracts. Arbitrary extra fields are rejected."""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class CheckInput(Input):
    application_id: str = Field(min_length=1, max_length=100)
    operation_id: str = Field(min_length=1, max_length=100)
    action: str = Field(min_length=1, max_length=100)
    initiator: str = Field(min_length=1, max_length=100)
    record_key: str | None = None
    fields: dict[str, Any]


class EventInput(Input):
    application_id: str
    event_id: str = Field(min_length=1, max_length=100)
    event_at: datetime
    action: str
    actor: str
    status: str
    fields: dict[str, Any]
    operation_id: str | None = None
    decision_id: str | None = None

    @field_validator("event_at")
    @classmethod
    def aware_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("Время события должно включать часовой пояс")
        return value


class RuleInput(Input):
    application_id: str
    name: str = Field(min_length=1, max_length=150)
    action: str
    expression: dict[str, Any]
    reaction: Literal["LOG", "BLOCK", "REVIEW", "CONFIRM"]
    enabled: bool = True
    exception: dict[str, Any] | None = None


class WatchlistInput(Input):
    name: str = Field(min_length=1, max_length=150)
    values: list[str | float | bool] = Field(max_length=10000)


class CreateWatchlistInput(WatchlistInput):
    application_id: str


class ApplicationInput(Input):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,60}$")
    name: str = Field(min_length=1, max_length=150)
    catalog: dict[str, dict[str, Any]]
    ttl_seconds: int = Field(ge=1, le=86400)


class ExpenseInput(Input):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    recipient: str = Field(min_length=1, max_length=100)
    receipt: str = Field(min_length=1, max_length=100)
    vendor: str = Field(min_length=1, max_length=100)
    purchase_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    title: str = Field(min_length=1, max_length=200)
    category: Literal["office", "transport", "other"] = "other"

    @field_validator("recipient", "receipt", "vendor", "title")
    @classmethod
    def meaningful_text(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Поле не может состоять только из пробелов")
        return value

    @field_validator("purchase_date")
    @classmethod
    def calendar_date(cls, value):
        date.fromisoformat(value)
        return value


class DemoCheck(Input):
    operation_id: str = Field(min_length=1, max_length=100)
    action: Literal["submit", "approve", "reject", "pay"]
    version: int | None = Field(default=None, ge=1)


class ExecuteInput(Input):
    operation_id: str
    decision_id: str


class OperationInput(Input):
    operation_id: str = Field(min_length=1, max_length=100)


class TransitionInput(Input):
    approve: bool
    comment: str = Field(default="", max_length=1000)


class ConfirmInput(TransitionInput):
    operation_id: str
    checked_values: dict[str, Any]


class ApplicationConfirmation(ConfirmInput):
    initiator: str


class ApplicationCancellation(OperationInput):
    initiator: str


class ResetInput(Input):
    confirmation: Literal["Вернуть учебное демо"]
