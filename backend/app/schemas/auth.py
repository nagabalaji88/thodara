import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.i18n import tr


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
    language: str = "en"


class LanguageRequest(BaseModel):
    language: Literal["en", "ta"]


class TwoStepState(BaseModel):
    """Where this session and user stand on two-step sign-in (ADR-0015)."""

    # "verify": enter an authenticator or backup code; "enrol": set up before continuing.
    stage: Literal["full", "verify", "enrol"] = "full"
    enabled: bool = False
    # Owners and administrators must use it.
    required: bool = False
    # Set while a required user is in the 7-day grace period (or past it).
    due_at: datetime | None = None
    backup_codes_left: int = 0


class SessionResponse(BaseModel):
    user: SessionUser
    active_tenant: TenantChoice | None
    memberships: list[TenantChoice]
    expires_at: datetime
    two_step: TwoStepState = Field(default_factory=TwoStepState)


class TwoStepCode(BaseModel):
    # An authenticator code (6 digits) or a backup code (XXXXX-XXXXX).
    code: str = Field(min_length=6, max_length=16)


class TwoStepSetup(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class TwoStepEnabled(BaseModel):
    backup_codes: list[str]
    session: SessionResponse


class BackupCodes(BaseModel):
    backup_codes: list[str]


class SessionInfo(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    user_agent: str | None
    current: bool


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
            raise ValueError(tr("Choose a valid IANA time zone")) from exc
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
