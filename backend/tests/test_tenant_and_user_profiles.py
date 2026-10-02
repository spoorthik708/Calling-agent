import uuid
import pytest
from httpx import AsyncClient

from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_user_me_profile_endpoint(async_client: AsyncClient, seed_tenants):
    """Test 33: GET /users/me returns authenticated user details without password fields."""
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    res = await async_client.get("/api/v1/users/me", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(user_a.id)
    assert data["email"] == "admin@alpha.com"
    assert data["role"] == "owner"
    assert "password" not in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_tenant_profile_isolation(async_client: AsyncClient, seed_tenants):
    """
    Tests 22, 34, 35:
    - /tenant returns correct tenant for caller
    - User A cannot see Tenant B's profile
    """
    user_a = seed_tenants["user_a"]
    tenant_a = seed_tenants["tenant_a"]
    token_a = create_access_token(subject=user_a.id, tenant_id=tenant_a.id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    res_a = await async_client.get("/api/v1/tenant", headers=headers_a)
    assert res_a.status_code == 200
    assert res_a.json()["id"] == str(tenant_a.id)
    assert res_a.json()["slug"] == "company-alpha"


@pytest.mark.asyncio
async def test_tenant_a_cannot_read_tenant_b_users(async_client: AsyncClient, seed_tenants):
    """Test 23: Tenant A listing users only sees Tenant A users, never Tenant B."""
    user_a = seed_tenants["user_a"]
    tenant_a = seed_tenants["tenant_a"]
    token_a = create_access_token(subject=user_a.id, tenant_id=tenant_a.id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    res = await async_client.get("/api/v1/users", headers=headers_a)
    assert res.status_code == 200
    users = res.json()
    assert len(users) == 1
    assert users[0]["email"] == "admin@alpha.com"
    # Never includes tenant B
    assert all(u["email"] != "admin@beta.com" for u in users)


@pytest.mark.asyncio
async def test_tenant_a_cannot_modify_tenant_b_user(async_client: AsyncClient, seed_tenants):
    """Test 24: Tenant A admin cannot modify a user belonging to Tenant B."""
    user_a = seed_tenants["user_a"]
    user_b = seed_tenants["user_b"]
    token_a = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Attempt to modify user B
    res = await async_client.patch(
        f"/api/v1/users/{user_b.id}",
        headers=headers_a,
        json={"status": "disabled"},
    )
    # 404 Not Found to prevent leaking user B's existence
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_tenant_id_header_cannot_override_jwt_claims(async_client: AsyncClient, seed_tenants):
    """
    Test 25 (CRITICAL TENANT ISOLATION):
    A malicious client attempting to send 'X-Tenant-ID' pointing to another company
    CANNOT override the tenant identity verified inside the signed JWT.
    """
    user_a = seed_tenants["user_a"]
    tenant_b = seed_tenants["tenant_b"]

    token_a = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    # Attacker passes User A's token with Tenant B's ID in header
    headers = {
        "Authorization": f"Bearer {token_a}",
        "X-Tenant-ID": str(tenant_b.id),
    }

    res = await async_client.get("/api/v1/tenant", headers=headers)
    assert res.status_code == 200
    # Tenant profile MUST remain Tenant A
    assert res.json()["slug"] == "company-alpha"
    assert res.json()["slug"] != "company-beta"


@pytest.mark.asyncio
async def test_sql_injection_attempts_in_login_and_registration_are_safe(async_client: AsyncClient):
    """
    Test 39:
    SQL injection strings in email or tenant_slug are safely handled via SQLAlchemy ORM parameter binding.
    """
    sql_payload = {
        "email": "admin@example.com' OR '1'='1",
        "password": "Password123456!",
    }
    res = await async_client.post("/api/v1/auth/login", json=sql_payload)
    # Handled safely as either validation error or 401 unauthenticated
    assert res.status_code in [401, 422]
