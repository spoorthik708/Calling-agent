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

    # Security
    SECRET_KEY: SecretStr = Field(
        default=SecretStr("insecure-default-change-in-production-must-be-32-chars-minimum"),
        description="Master encryption and JWT signing secret",
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

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

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
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
