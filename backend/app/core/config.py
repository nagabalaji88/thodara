from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="THODARA_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+asyncpg://thodara:change-me@localhost:5432/thodara"
    allowed_origins: list[str] = ["http://localhost:5173"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    session_ttl_hours: int = 8
    session_cookie_name: str = "thodara_session"
    csrf_cookie_name: str = "thodara_csrf"
    session_cookie_secure: bool = False
    login_lockout_attempts: int = 5
    login_lockout_minutes: int = 15

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, value: list[str]) -> list[str]:
        cleaned = [origin.rstrip("/") for origin in value]
        if "*" in cleaned:
            raise ValueError("Wildcard CORS origins are not allowed")
        url_type = TypeAdapter(AnyHttpUrl)
        for origin in cleaned:
            url_type.validate_python(origin)
        return cleaned

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.session_ttl_hours < 1 or self.session_ttl_hours > 24:
            raise ValueError("Session TTL must be between 1 and 24 hours")
        if self.app_env == "production":
            if not self.session_cookie_secure:
                raise ValueError("Secure session cookies are required in production")
            if not self.allowed_origins or not self.allowed_hosts:
                raise ValueError("Production origins and hosts must be explicitly configured")
            if "localhost" in self.allowed_hosts or "127.0.0.1" in self.allowed_hosts:
                raise ValueError("Development hosts must not be enabled in production")
            if "localhost" in self.database_url:
                raise ValueError("Production database URL must not point to localhost")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
