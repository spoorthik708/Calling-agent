import os
from functools import lru_cache
from typing import List, Optional
from pydantic import Field, SecretStr, field_validator, model_validator
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
    TELEPHONY_PROVIDER: str = Field(default="mock", description="mock, twilio, exotel")
    TELEPHONY_WEBHOOK_SECRET: Optional[SecretStr] = None
    TWILIO_ACCOUNT_SID: str = Field(default="mock_twilio_sid")
    TWILIO_AUTH_TOKEN: Optional[SecretStr] = None
    EXOTEL_ACCOUNT_SID: str = Field(default="mock_exotel_sid")
    EXOTEL_API_KEY: Optional[SecretStr] = None
    EXOTEL_API_TOKEN: Optional[SecretStr] = None
    EXOTEL_SUBDOMAIN: str = Field(default="api.exotel.com")
    EXOTEL_SIGNATURE_SECRET: Optional[SecretStr] = None
    EXOTEL_OUTBOUND_PROMOTIONAL_SERIES: str = Field(
        default="140",
        description="TRAI mandated 140-series prefix for Indian promotional commercial communications",
    )

    # Reverse Proxy & Rate Limiting (SEC-06)
    TRUST_PROXY_HEADERS: bool = Field(
        default=False,
        description="Whether to trust forwarding headers (e.g. X-Forwarded-For) from reverse proxies",
    )
    TRUSTED_PROXY_IPS: List[str] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"],
        description="List of trusted reverse proxy IP addresses allowed to forward client identity",
    )

    # Knowledge Base & RAG Settings (Phase 3)
    KNOWLEDGE_STORAGE_PATH: str = Field(default="storage/documents")
    MAX_UPLOAD_SIZE_BYTES: int = Field(
        default=10 * 1024 * 1024,
        description="Maximum upload file size in bytes (10MB default)",
    )
    ALLOWED_DOCUMENT_TYPES: List[str] = Field(
        default_factory=lambda: ["text/plain", "application/pdf"],
        description="Permitted document MIME types for ingestion",
    )
    EMBEDDING_PROVIDER: str = Field(
        default="mock",
        description="Active embedding provider: mock, openai, etc.",
    )
    EMBEDDING_MODEL: str = Field(
        default="text-embedding-3-small",
        description="Model name for generating vector embeddings",
    )
    EMBEDDING_DIMENSION: int = Field(
        default=1536,
        description="Vector dimension for embeddings (e.g. 1536 for OpenAI small)",
    )
    CHUNK_SIZE: int = Field(
        default=500,
        description="Target character length for document text chunks",
    )
    CHUNK_OVERLAP: int = Field(
        default=50,
        description="Character overlap between consecutive chunks",
    )
    RETRIEVAL_TOP_K: int = Field(
        default=5,
        description="Default number of top matching chunks to retrieve",
    )
    RETRIEVAL_MIN_SIMILARITY: float = Field(
        default=0.30,
        description="Minimum cosine similarity threshold to consider relevant",
    )
    RETRIEVAL_CONFIDENCE_THRESHOLD: float = Field(
        default=0.40,
        description="Threshold above which retrieval is considered high confidence FOUND",
    )

    MAX_DOCUMENT_PAGES: int = Field(
        default=500,
        description="Maximum allowed pages in a single PDF document",
    )
    MAX_DOCUMENT_CHUNKS: int = Field(
        default=1000,
        description="Maximum allowed chunks generated from a single document",
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

    # Agent & Conversation Runtime Settings (Phase 4)
    DEFAULT_LLM_PROVIDER: str = Field(
        default="mock",
        description="Active LLM provider for conversational runtime: mock, openai, etc.",
    )
    DEFAULT_LLM_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Default LLM model name for agent conversational turns",
    )
    MAX_CONVERSATION_HISTORY_MESSAGES: int = Field(
        default=20,
        description="Maximum recent conversation messages included in LLM context",
    )
    MAX_CONVERSATION_MESSAGE_CHARS: int = Field(
        default=4000,
        description="Maximum allowed characters for a single user utterance/message",
    )
    CONVERSATION_IDEMPOTENCY_EXPIRE_HOURS: int = Field(
        default=24,
        description="Hours before idempotency keys expire",
    )
    CONVERSATION_RATE_LIMIT_PER_MINUTE: int = Field(
        default=60,
        description="Maximum conversational execution turns allowed per tenant/user per minute",
    )

    # Tool & Action Layer Settings (Phase 5)
    MAX_TOOL_CALLS_PER_TURN: int = Field(
        default=3,
        description="Maximum sequential tool calls permitted per conversational turn",
    )
    DEFAULT_TOOL_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="Default timeout in seconds for external and internal tool execution",
    )
    TOOL_IDEMPOTENCY_EXPIRE_HOURS: int = Field(
        default=24,
        description="Hours before tool execution idempotency keys expire",
    )
    TOOL_RATE_LIMIT_PER_MINUTE: int = Field(
        default=120,
        description="Maximum tool executions allowed per tenant per minute",
    )
    SSRF_ALLOW_HTTP_FOR_TESTING: bool = Field(
        default=False,
        description="Whether to permit HTTP scheme for local testing (production requires HTTPS)",
    )
    MAX_HTTP_TOOL_RESPONSE_BYTES: int = Field(
        default=2 * 1024 * 1024,
        description="Maximum allowed HTTP response body size in bytes (2MB default)",
    )
    MAX_TOOL_ARGUMENT_BYTES: int = Field(
        default=64 * 1024,
        description="Maximum allowed JSON size in bytes for tool input arguments (64KB default)",
    )
    MAX_HTTP_TOOL_REDIRECTS: int = Field(
        default=3,
        description="Maximum allowed validated redirect hops for HTTP tools",
    )

    # Phase 6: Production Voice Layer Settings
    DEFAULT_STT_PROVIDER: str = Field(
        default="mock",
        description="Default Speech-to-Text provider (e.g. 'deepgram', 'whisper', 'mock')",
    )
    DEFAULT_TTS_PROVIDER: str = Field(
        default="mock",
        description="Default Text-to-Speech provider (e.g. 'elevenlabs', 'cartesia', 'mock')",
    )
    DEFAULT_VAD_PROVIDER: str = Field(
        default="energy",
        description="Default Voice Activity Detection provider ('energy', 'webrtc', 'mock')",
    )
    VOICE_TRANSCRIPT_RETENTION_ENABLED: bool = Field(
        default=True,
        description="Whether finalized voice transcripts are persisted to conversation memory",
    )
    VOICE_AUDIO_RETENTION_ENABLED: bool = Field(
        default=False,
        description="Privacy invariant: Whether raw audio frames are stored (default False, ephemeral)",
    )
    MAX_AUDIO_CHUNK_BYTES: int = Field(
        default=64 * 1024,
        description="Maximum allowed single audio chunk size in bytes (64KB default)",
    )
    MAX_AUDIO_BUFFER_BYTES: int = Field(
        default=5 * 1024 * 1024,
        description="Maximum allowed accumulated audio buffer per turn (5MB default)",
    )
    MAX_AUDIO_QUEUE_SIZE: int = Field(
        default=100,
        description="Maximum capacity of asynchronous audio frame queues before backpressure",
    )
    MAX_TURN_DURATION_SECONDS: float = Field(
        default=30.0,
        description="Maximum duration of continuous speech permitted in a single turn",
    )
    DEFAULT_SILENCE_TIMEOUT_SECONDS: float = Field(
        default=1.0,
        description="Duration of silence required to detect turn completion",
    )
    DEFAULT_MIN_SPEECH_DURATION_SECONDS: float = Field(
        default=0.2,
        description="Minimum duration of speech required to register speech start",
    )
    STT_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="Bounded timeout for speech-to-text transcription",
    )
    TTS_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="Bounded timeout for speech synthesis",
    )
    LLM_STREAM_TIMEOUT_SECONDS: float = Field(
        default=15.0,
        description="Bounded timeout for streaming LLM generation chunks",
    )
    VOICE_SESSION_RATE_LIMIT_PER_MINUTE: int = Field(
        default=30,
        description="Rate limit on voice session creation per tenant per minute",
    )
    VOICE_AUDIO_RATE_LIMIT_PER_MINUTE: int = Field(
        default=600,
        description="Rate limit on audio chunk ingestion per tenant per minute",
    )

    @model_validator(mode="after")
    def validate_knowledge_and_retrieval_settings(self) -> "Settings":
        if self.RETRIEVAL_MIN_SIMILARITY > self.RETRIEVAL_CONFIDENCE_THRESHOLD:
            raise ValueError(
                f"RETRIEVAL_MIN_SIMILARITY ({self.RETRIEVAL_MIN_SIMILARITY}) cannot be greater than "
                f"RETRIEVAL_CONFIDENCE_THRESHOLD ({self.RETRIEVAL_CONFIDENCE_THRESHOLD})"
            )
        if self.is_production and self.EMBEDDING_PROVIDER.lower() == "mock":
            raise ValueError(
                "Mock embedding provider is strictly prohibited in production. "
                "Configure a valid EMBEDDING_PROVIDER."
            )
        if self.EMBEDDING_PROVIDER.lower() == "openai" and not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY must be provided when EMBEDDING_PROVIDER is 'openai'")
        if self.is_production and self.DEFAULT_LLM_PROVIDER.lower() == "mock":
            raise ValueError(
                "Mock LLM provider is strictly prohibited in production. "
                "Configure a valid DEFAULT_LLM_PROVIDER."
            )
        if self.DEFAULT_LLM_PROVIDER.lower() == "openai" and not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY must be provided when DEFAULT_LLM_PROVIDER is 'openai'")
        if self.is_production and self.DEFAULT_STT_PROVIDER.lower() == "mock":
            raise ValueError(
                "Mock STT provider is strictly prohibited in production. "
                "Configure a valid DEFAULT_STT_PROVIDER."
            )
        if self.is_production and self.DEFAULT_TTS_PROVIDER.lower() == "mock":
            raise ValueError(
                "Mock TTS provider is strictly prohibited in production. "
                "Configure a valid DEFAULT_TTS_PROVIDER."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache()
def get_settings() -> Settings:
    """Returns cached settings instance."""
    return Settings()
