import os
from functools import lru_cache
from typing import List, Optional
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings with environment variable loading and validation.
    Secrets are wrapped in SecretStr to prevent accidental exposure or logging.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "yavura-api"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = Field(default="development", description="development, staging, production")
    DEBUG: bool = Field(default=False)
    PORT: int = Field(default=8000)
    HOST: str = Field(default="0.0.0.0")

    # Security & JWT Authentication
    SECRET_KEY: SecretStr = Field(
        default=SecretStr("insecure-default-change-in-production-must-be-32-chars-minimum"),
        description="Master encryption and JWT signing secret",
    )
    JWT_SECRET_KEY: Optional[SecretStr] = Field(
        default=None,
        description="Optional explicit JWT signing secret, falls back to SECRET_KEY if not provided",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: Optional[int] = None
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: Optional[int] = None

    @property
    def jwt_secret(self) -> str:
        if self.JWT_SECRET_KEY is not None:
            return self.JWT_SECRET_KEY.get_secret_value()
        return self.SECRET_KEY.get_secret_value()

    @property
    def access_token_expire_minutes(self) -> int:
        if self.JWT_ACCESS_TOKEN_EXPIRE_MINUTES is not None:
            return self.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        return self.ACCESS_TOKEN_EXPIRE_MINUTES

    @property
    def refresh_token_expire_days(self) -> int:
        if self.JWT_REFRESH_TOKEN_EXPIRE_DAYS is not None:
            return self.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        return self.REFRESH_TOKEN_EXPIRE_DAYS

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://yavura_user:yavura_password@localhost:5432/yavura_db",
        description="Async database connection string",
    )
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_TIMEOUT: int = 30

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # Multi-tenancy
    DEFAULT_TENANT_ID: Optional[str] = None

    # AI Provider Settings (Abstracted)
    DEFAULT_AI_PROVIDER: str = "mock"
    AI_REQUEST_TIMEOUT_SECONDS: int = 30
    OPENAI_API_KEY: Optional[SecretStr] = None
    ANTHROPIC_API_KEY: Optional[SecretStr] = None
    GEMINI_API_KEY: Optional[SecretStr] = None

    # Telephony Provider Settings (Abstracted)
    TELEPHONY_PROVIDER: str = "mock"
    TELEPHONY_WEBHOOK_SECRET: Optional[SecretStr] = None

    # Reverse Proxy & Rate Limiting (SEC-06)
    TRUST_PROXY_HEADERS: bool = Field(
        default=False,
        description="Whether to trust forwarding headers (e.g. X-Forwarded-For) from reverse proxies",
    )
    TRUSTED_PROXY_IPS: List[str] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"],
        description="List of trusted reverse proxy IP addresses allowed to forward client identity",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    @field_validator("TRUSTED_PROXY_IPS", mode="before")
    @classmethod
    def assemble_trusted_proxy_ips(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache()
def get_settings() -> Settings:
    """Returns cached settings instance."""
    return Settings()
