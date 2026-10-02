import pytest
from pydantic import SecretStr
from app.core.config import Settings


def test_settings_secret_masking():
    """Verifies that secrets are masked using SecretStr and not exposed in strings."""
    settings = Settings(
        SECRET_KEY=SecretStr("super-confidential-secret-key-12345"),
        OPENAI_API_KEY=SecretStr("sk-test-key-123"),
    )
    # String representation must not expose secret
    assert "super-confidential" not in str(settings)
    assert "sk-test-key" not in str(settings)
    # Explicit value access works
    assert settings.SECRET_KEY.get_secret_value() == "super-confidential-secret-key-12345"


def test_cors_origins_parsing():
    """Verifies parsing of comma-separated string CORS origins."""
    settings = Settings(CORS_ORIGINS="http://localhost:3000, https://app.yavura.com")
    assert "http://localhost:3000" in settings.CORS_ORIGINS
    assert "https://app.yavura.com" in settings.CORS_ORIGINS
