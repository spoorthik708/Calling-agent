from datetime import timedelta
import uuid
import pytest
from httpx import AsyncClient

from app.core.logging import sanitize_dict
from app.core.security import create_access_token, decode_access_token, get_password_hash, verify_password


@pytest.mark.asyncio
async def test_successful_login(async_client: AsyncClient, seed_tenants):
    """Test 8: Successful login with valid email and password."""
    login_payload = {
        "email": "admin@alpha.com",
        "password": "password123456",
    }
    response = await async_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "admin@alpha.com"
    assert data["tenant"]["slug"] == "company-alpha"


@pytest.mark.asyncio
async def test_wrong_password_rejected(async_client: AsyncClient, seed_tenants):
    """Test 9: Wrong password returns 401 generic failure."""
    login_payload = {
        "email": "admin@alpha.com",
        "password": "WrongPassword123!",
    }
    response = await async_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_unknown_email_returns_generic_failure(async_client: AsyncClient, seed_tenants):
    """
    Test 10: Unknown email returns exact same generic 401 failure
    to eliminate user enumeration vectors.
    """
    login_payload = {
        "email": "nonexistent_user@example.com",
        "password": "AnyPassword123!",
    }
    response = await async_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_access_token_claims_structure():
    """
    Test 11:
    Access token contains strictly intended claims:
    sub, tenant_id, role, type="access", jti, iat, exp.
    Contains NO personal information, passwords, or customer data.
    """
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    token = create_access_token(
        subject=user_id,
        tenant_id=tenant_id,
        role="owner",
    )
    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "owner"
    assert payload["type"] == "access"
    assert "jti" in payload
    assert "iat" in payload
    assert "exp" in payload

    # Ensure no sensitive claims
    forbidden_keys = ["password", "password_hash", "hashed_password", "email", "secret", "credit_card"]
    for key in forbidden_keys:
        assert key not in payload


@pytest.mark.asyncio
async def test_expired_access_token_rejected(async_client: AsyncClient, seed_tenants):
    """Test 12: Expired access token rejected with 401."""
    user_a = seed_tenants["user_a"]
    expired_token = create_access_token(
        subject=user_a.id,
        tenant_id=user_a.tenant_id,
        role=user_a.role,
        expires_delta=timedelta(seconds=-10),  # expired 10 seconds ago
    )
    headers = {"Authorization": f"Bearer {expired_token}"}
    response = await async_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
    assert "invalid or expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invalid_access_token_rejected(async_client: AsyncClient):
    """Test 13: Tampered or invalid access token rejected with 401."""
    headers = {"Authorization": "Bearer invalid.gibberish.token"}
    response = await async_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
    assert "invalid or expired" in response.json()["detail"].lower()


def test_secrets_and_passwords_are_scrubbed_from_logs():
    """
    Tests 36 & 37:
    Sanitizer properly scrubs passwords, secrets, and auth tokens.
    """
    raw_payload = {
        "email": "user@example.com",
        "password": "SuperSecretPassword123!",
        "access_token": "eyJhbGciOi...",
        "api_key": "sk-1234567890",
        "user_profile": {
            "first_name": "Alice",
            "secret_key": "private_secret_value",
        }
    }
    sanitized = sanitize_dict(raw_payload)
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["user_profile"]["secret_key"] == "[REDACTED]"
    assert sanitized["user_profile"]["first_name"] == "Alice"


# ==============================================================================
# SEC-01: BCRYPT PASSWORD LENGTH & UNICODE HANDLING
# ==============================================================================

@pytest.mark.asyncio
async def test_password_exceeding_bcrypt_byte_limit_returns_401_not_500(async_client: AsyncClient, seed_tenants):
    """
    SEC-01 Regression Test:
    A password exceeding bcrypt's 72-byte limit must NOT raise ValueError (causing a 500 error).
    It must produce a normal 401 authentication failure.
    """
    # 100 character password > 72 bytes
    long_password = "A" * 100
    login_payload = {
        "email": "admin@alpha.com",
        "password": long_password,
    }
    response = await async_client.post("/api/v1/auth/login", json=login_payload)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_verify_password_unit_with_oversized_and_unicode_inputs():
    """
    SEC-01 Unit Test:
    - Normal valid password authenticates.
    - Password > 72 bytes does not crash with ValueError and safely compares truncated bytes.
    - Unicode characters are handled based on UTF-8 encoded byte length, not Python char count.
    """
    plain = "ValidPassword123!"
    h = get_password_hash(plain)
    assert verify_password(plain, h) is True
    assert verify_password("WrongPassword123!", h) is False

    # Oversized string > 72 bytes
    oversized = "X" * 150
    # Must not raise ValueError
    assert verify_password(oversized, h) is False

    # Unicode multibyte test:
    # '€' is 3 bytes in UTF-8. 25 chars of '€' = 75 bytes (> 72 bytes) even though len() is 25!
    unicode_pwd = "€" * 25
    assert len(unicode_pwd) == 25
    assert len(unicode_pwd.encode("utf-8")) == 75

    unicode_hash = get_password_hash(unicode_pwd)
    # verify_password handles encoded byte length consistently with hashing
    assert verify_password(unicode_pwd, unicode_hash) is True
    # Different unicode string of same character length fails safely without crash
    assert verify_password("£" * 25, unicode_hash) is False


# ==============================================================================
# SEC-05: LOGIN TIMING SIDE CHANNEL & ENUMERATION RESISTANCE
# ==============================================================================

@pytest.mark.asyncio
async def test_unknown_email_and_incorrect_password_produce_identical_external_response(
    async_client: AsyncClient,
    seed_tenants,
):
    """
    SEC-05 Regression Test:
    Confirms that authentication attempts for unknown email and incorrect password
    both produce the identical external HTTP status, header, and response payload.
    """
    # 1. Existing user with wrong password
    wrong_pwd_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.com", "password": "WrongPassword999!"},
    )

    # 2. Non-existent user
    unknown_user_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent.user.audit@nowhere.com", "password": "WrongPassword999!"},
    )

    assert wrong_pwd_res.status_code == 401
    assert unknown_user_res.status_code == 401
    assert wrong_pwd_res.json() == unknown_user_res.json()
    assert wrong_pwd_res.headers.get("www-authenticate") == unknown_user_res.headers.get("www-authenticate")

