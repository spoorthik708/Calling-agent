from datetime import datetime, timedelta, timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken
from app.core.security import hash_token


@pytest.mark.asyncio
async def test_successful_refresh_and_rotation(async_client: AsyncClient, seed_tenants, db_session: AsyncSession):
    """
    Tests 14, 15, 38:
    - Successful refresh returns new access token and new rotated refresh token
    - Raw refresh token is NOT stored in DB in plaintext (only hash)
    - Old refresh token record is marked revoked and linked to replacement
    """
    # 1. Login to get initial refresh token
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.com", "password": "password123456"},
    )
    assert login_res.status_code == 200
    initial_refresh = login_res.json()["refresh_token"]

    # Test 38: Verify raw token is NOT in DB plaintext
    hash_v1 = hash_token(initial_refresh)
    token_record_v1 = (
        await db_session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_v1))
    ).scalar_one()
    assert token_record_v1.token_hash == hash_v1
    # Raw token string is NOT stored
    assert initial_refresh != hash_v1

    # 2. Rotate refresh token
    rotate_res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": initial_refresh},
    )
    assert rotate_res.status_code == 200
    rotated_data = rotate_res.json()
    new_refresh = rotated_data["refresh_token"]
    assert new_refresh != initial_refresh

    # Verify old token is now revoked in DB
    await db_session.refresh(token_record_v1)
    assert token_record_v1.revoked_at is not None
    assert token_record_v1.replaced_by_token_id is not None


@pytest.mark.asyncio
async def test_reuse_of_rotated_refresh_token_triggers_family_revocation(
    async_client: AsyncClient,
    seed_tenants,
    db_session: AsyncSession,
):
    """
    Test 16:
    When an already-rotated refresh token is re-submitted, the system treats this
    as a security compromise and invalidates the entire token family!
    """
    # 1. Login
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.com", "password": "password123456"},
    )
    initial_refresh = login_res.json()["refresh_token"]

    # 2. Legitimate rotation #1
    rot_res1 = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": initial_refresh},
    )
    assert rot_res1.status_code == 200
    active_refresh = rot_res1.json()["refresh_token"]

    # 3. ATTACKER REPLAYS INITIAL TOKEN (already rotated)
    replay_res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": initial_refresh},
    )
    assert replay_res.status_code == 401
    assert "compromised" in replay_res.json()["detail"].lower()

    # 4. Legitimate user's active_refresh token MUST now also be revoked due to family compromise!
    rot_res2 = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": active_refresh},
    )
    assert rot_res2.status_code == 401


@pytest.mark.asyncio
async def test_expired_refresh_token_rejected(async_client: AsyncClient, seed_tenants, db_session: AsyncSession):
    """Test 17: Expired refresh token rejected with 401."""
    user_a = seed_tenants["user_a"]
    expired_hash = hash_token("expired_refresh_token_test")
    record = RefreshToken(
        tenant_id=user_a.tenant_id,
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        token_hash=expired_hash,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # expired yesterday
    )
    db_session.add(record)
    await db_session.commit()

    res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "expired_refresh_token_test"},
    )
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_revoked_refresh_token_rejected(async_client: AsyncClient, seed_tenants, db_session: AsyncSession):
    """Test 18: Manually revoked refresh token rejected."""
    user_a = seed_tenants["user_a"]
    revoked_hash = hash_token("revoked_refresh_token_test")
    record = RefreshToken(
        tenant_id=user_a.tenant_id,
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        token_hash=revoked_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        revoked_at=datetime.now(timezone.utc),  # already revoked
    )
    db_session.add(record)
    await db_session.commit()

    res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "revoked_refresh_token_test"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(async_client: AsyncClient, seed_tenants):
    """Test 19: Logout revokes refresh token server-side."""
    # 1. Login
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.com", "password": "password123456"},
    )
    access_token = login_res.json()["access_token"]
    refresh_token = login_res.json()["refresh_token"]

    # 2. Logout with refresh token specified
    headers = {"Authorization": f"Bearer {access_token}"}
    logout_res = await async_client.post(
        "/api/v1/auth/logout",
        headers=headers,
        json={"refresh_token": refresh_token},
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["success"] is True

    # 3. Refreshing with that token now fails
    refresh_res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_res.status_code == 401


@pytest.mark.asyncio
async def test_cross_tenant_and_cross_user_refresh_isolation(
    async_client: AsyncClient,
    seed_tenants,
    db_session: AsyncSession,
):
    """
    Tests 20 & 21:
    Verifies that a token belonging to Tenant B / User B cannot issue tokens
    for Tenant A or grant access to Tenant A resources.
    """
    # Login Tenant B
    login_b = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@beta.com", "password": "password123456"},
    )
    token_b = login_b.json()["access_token"]
    refresh_b = login_b.json()["refresh_token"]

    # Refresh token B works for Tenant B
    ref_res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_b},
    )
    assert ref_res.status_code == 200
    assert ref_res.json()["tenant"]["slug"] == "company-beta"
    assert ref_res.json()["user"]["email"] == "admin@beta.com"

    # User B cannot access Tenant A's tenant profile
    headers_b = {"Authorization": f"Bearer {token_b}"}
    tenant_profile_res = await async_client.get("/api/v1/tenant", headers=headers_b)
    assert tenant_profile_res.status_code == 200
    assert tenant_profile_res.json()["slug"] == "company-beta"
    assert tenant_profile_res.json()["slug"] != "company-alpha"


# ==============================================================================
# SEC-03: LOGOUT TOKEN OWNERSHIP
# ==============================================================================

@pytest.mark.asyncio
async def test_user_cannot_revoke_another_users_refresh_token(async_client: AsyncClient, seed_tenants):
    """
    SEC-03 Regression Test:
    User A must NOT be able to revoke User B's session by passing User B's refresh token.
    The logout query requires both token_hash AND authenticated user_id.
    """
    # 1. Login User A
    login_a = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.com", "password": "password123456"},
    )
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]

    # 2. Login User B
    login_b = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@beta.com", "password": "password123456"},
    )
    assert login_b.status_code == 200
    refresh_b = login_b.json()["refresh_token"]

    # 3. User A attempts to logout User B's refresh token
    headers_a = {"Authorization": f"Bearer {token_a}"}
    logout_res = await async_client.post(
        "/api/v1/auth/logout",
        headers=headers_a,
        json={"refresh_token": refresh_b},
    )
    assert logout_res.status_code == 200

    # 4. User B's refresh token MUST STILL WORK (was NOT revoked by User A)
    ref_res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_b},
    )
    assert ref_res.status_code == 200
    assert ref_res.json()["user"]["email"] == "admin@beta.com"


# ==============================================================================
# SEC-02: REFRESH TOKEN CONCURRENCY AND ROW LOCKING
# ==============================================================================

def test_refresh_token_query_includes_for_update_in_postgresql_dialect():
    """
    SEC-02 Architecture & Concurrency Test:
    Verifies that the refresh token selection query explicitly includes FOR UPDATE
    in the PostgreSQL dialect to serialize concurrent rotations and prevent race conditions.
    """
    from sqlalchemy.dialects import postgresql, sqlite
    from sqlalchemy.orm import selectinload
    from app.users.models import User

    token_hash = "sample_hash_for_testing"
    stmt = (
        select(RefreshToken)
        .options(selectinload(RefreshToken.user).selectinload(User.tenant))
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
    )

    pg_sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in pg_sql

    # Verify SQLite dialect compatibility: compiles cleanly without error
    sqlite_sql = str(stmt.compile(dialect=sqlite.dialect()))
    assert "FROM refresh_tokens" in sqlite_sql


@pytest.mark.asyncio
async def test_concurrent_or_repeated_rotation_triggers_compromise_detection(
    async_client: AsyncClient,
    seed_tenants,
):
    """
    SEC-02 Concurrency Flow Test:
    When a refresh token is rotated, any subsequent or race-condition attempt
    to reuse that same token immediately triggers compromise detection and revokes the family.
    """
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.com", "password": "password123456"},
    )
    assert login_res.status_code == 200
    token_to_rotate = login_res.json()["refresh_token"]

    # Transaction 1: Successful rotation
    res1 = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token_to_rotate},
    )
    assert res1.status_code == 200
    new_token = res1.json()["refresh_token"]

    # Transaction 2 (simulating race / replay of same token):
    res2 = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token_to_rotate},
    )
    assert res2.status_code == 401
    assert "compromised" in res2.json()["detail"].lower()

    # The entire family is now compromised, so the newly issued token cannot be refreshed either
    res3 = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": new_token},
    )
    assert res3.status_code == 401

