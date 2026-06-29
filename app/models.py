from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID


class MessageCreate(BaseModel):
    source: str
    wmo_heading: str | None = None
    awips_id: str | None = None
    pil_code: str
    office: str
    product_text: str
    expires_at: datetime | None = None


class Message(BaseModel):
    id: UUID
    received_at: datetime
    source: str
    wmo_heading: str | None = None
    awips_id: str | None = None
    pil_code: str
    office: str
    product_text: str
    is_deleted: bool = False
    deleted_at: datetime | None = None
    expires_at: datetime | None = None


class MessageList(BaseModel):
    messages: list[Message]
    total: int
    page: int
    page_size: int


class FilterCreate(BaseModel):
    name: str
    type: str = Field(..., pattern="^(product|office|zone|location)$")
    mode: str = Field(..., pattern="^(include|exclude)$")
    values: list[str]
    enabled: bool = True


class FilterUpdate(BaseModel):
    name: str | None = None
    type: str | None = Field(None, pattern="^(product|office|zone|location)$")
    mode: str | None = Field(None, pattern="^(include|exclude)$")
    values: list[str] | None = None
    enabled: bool | None = None


class Filter(BaseModel):
    id: UUID
    name: str
    type: str
    mode: str
    values: list[str]
    enabled: bool = True
    created_at: datetime


class Settings(BaseModel):
    retention_days: int = 30
    api_poll_interval: int = 30
    data_source: str = "api"


class SettingsUpdate(BaseModel):
    retention_days: int | None = None
    api_poll_interval: int | None = None
    data_source: str | None = None


class Status(BaseModel):
    nwws_oi: str = "disconnected"
    api: str = "disconnected"
    api_last_poll: datetime | None = None
    api_messages_count: int = 0
    total_messages: int = 0
    deleted_messages: int = 0
    uptime_seconds: float = 0
