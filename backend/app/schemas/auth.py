import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TenantChoice(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    role: str


class SessionUser(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_name: str


class SessionResponse(BaseModel):
    user: SessionUser
    active_tenant: TenantChoice | None
    memberships: list[TenantChoice]
    expires_at: datetime


class SelectTenantRequest(BaseModel):
    tenant_id: uuid.UUID


class WorkspaceSetupRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=160)
    country_code: str = Field(min_length=2, max_length=2, pattern="^[A-Z]{2}$")
    base_currency: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    site_name: str = Field(min_length=2, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    time_zone: str = Field(min_length=1, max_length=64)

    @field_validator("time_zone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Choose a valid IANA time zone") from exc
        return value


class WorkspaceSite(BaseModel):
    id: uuid.UUID
    name: str
    city: str | None
    time_zone: str
    model_config = ConfigDict(from_attributes=True)


class WorkspaceSummary(BaseModel):
    tenant_id: uuid.UUID
    company_name: str
    country_code: str | None
    base_currency: str | None
    setup_complete: bool
    sites: list[WorkspaceSite]
    module_state: str = "not_configured"
    permissions: list[str] = []
