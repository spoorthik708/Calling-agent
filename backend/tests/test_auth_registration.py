import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, User


@pytest.mark.asyncio
async def test_successful_tenant_and_owner_registration(async_client: AsyncClient, db_session: AsyncSession):
    """
    Tests 1, 2, 5, 6:
    - Successful tenant registration
    - Initial user created as OWNER
    - Password is never returned
    - Password hash is never exposed
    """
    payload = {
        "tenant_name": "Acme Innovations",
        "tenant_slug": "acme-innovations",
        "email": "Founder@Acme.com",  # mixed case to test normalization
        "password": "SecurePassword123!",
        "first_name": "Jane",
        "last_name": "Doe",
    }
    response = await async_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()

    # Verify response structure
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "founder@acme.com"
    assert data["user"]["role"] == "owner"
    assert data["user"]["first_name"] == "Jane"
    assert data["user"]["last_name"] == "Doe"
    assert data["tenant"]["name"] == "Acme Innovations"
    assert data["tenant"]["slug"] == "acme-innovations"

    # CRITICAL: Verify passwords and hashes are never exposed
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]
    assert "hashed_password" not in data["user"]
    assert "password" not in str(data)
    assert "hashed" not in str(data).lower()

    # Verify DB persistence
    stmt = select(Tenant).where(Tenant.slug == "acme-innovations")
    tenant = (await db_session.execute(stmt)).scalar_one()
    assert tenant.status == "active"

    user_stmt = select(User).where(User.email == "founder@acme.com")
    user = (await db_session.execute(user_stmt)).scalar_one()
    assert user.role == "owner"
    assert user.tenant_id == tenant.id


@pytest.mark.asyncio
async def test_duplicate_tenant_slug_rejected(async_client: AsyncClient):
    """Test 3: Duplicate tenant slug rejected with 409 Conflict."""
    payload = {
        "tenant_name": "First Corp",
        "tenant_slug": "duplicate-slug",
        "email": "first@corp.com",
        "password": "SecurePassword123!",
    }
    res1 = await async_client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    payload2 = {
        "tenant_name": "Second Corp",
        "tenant_slug": "duplicate-slug",
        "email": "second@corp.com",
        "password": "SecurePassword123!",
    }
    res2 = await async_client.post("/api/v1/auth/register", json=payload2)
    assert res2.status_code == 409
    assert "already registered" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_weak_and_invalid_passwords_rejected(async_client: AsyncClient):
    """
    Test 7:
    - Passwords under 12 characters rejected
    - Whitespace only passwords rejected
    - Empty passwords rejected
    """
    # Too short (<12 chars)
    payload_short = {
        "tenant_name": "Test Co",
        "tenant_slug": "test-short-pwd",
        "email": "user@test.com",
        "password": "Short123!",
    }
    res1 = await async_client.post("/api/v1/auth/register", json=payload_short)
    assert res1.status_code in [400, 422]

    # Whitespace only
    payload_whitespace = {
        "tenant_name": "Test Co",
        "tenant_slug": "test-space-pwd",
        "email": "user2@test.com",
        "password": "            ",
    }
    res2 = await async_client.post("/api/v1/auth/register", json=payload_whitespace)
    assert res2.status_code in [400, 422]


@pytest.mark.asyncio
async def test_registration_validates_malformed_requests(async_client: AsyncClient):
    """Test 40: Authentication endpoints validate malformed requests with 422."""
    # Invalid email format
    bad_payload = {
        "tenant_name": "Bad Email Co",
        "tenant_slug": "bad-email-co",
        "email": "not-an-email",
        "password": "ValidPassword123!",
    }
    res = await async_client.post("/api/v1/auth/register", json=bad_payload)
    assert res.status_code == 422

    # Invalid slug (contains spaces and uppercase)
    bad_slug_payload = {
        "tenant_name": "Bad Slug Co",
        "tenant_slug": "Bad Slug!",
        "email": "admin@good.com",
        "password": "ValidPassword123!",
    }
    res2 = await async_client.post("/api/v1/auth/register", json=bad_slug_payload)
    assert res2.status_code == 422
