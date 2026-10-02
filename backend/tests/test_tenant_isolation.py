import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import (
    TenantContext,
    clear_current_tenant_context,
    set_current_tenant_context,
)
from app.core.exceptions import TenantIsolationError
from app.models import Tenant, User
from app.security.tenant_isolation import (
    assert_entity_tenant,
    enforce_current_tenant_filter,
    enforce_tenant_filter,
)


@pytest.mark.asyncio
async def test_tenant_data_isolation(db_session: AsyncSession, seed_tenants):
    """
    CRITICAL SAAS REQUIREMENT:
    Verifies that company A can NEVER retrieve company B data.
    """
    tenant_a = seed_tenants["tenant_a"]
    tenant_b = seed_tenants["tenant_b"]

    # Query users filtering strictly by tenant A
    query_a = enforce_tenant_filter(select(User), User, tenant_a.id)
    result_a = await db_session.execute(query_a)
    users_a = result_a.scalars().all()

    assert len(users_a) == 1
    assert users_a[0].email == "admin@alpha.com"
    assert str(users_a[0].tenant_id) == str(tenant_a.id)

    # Query users filtering strictly by tenant B
    query_b = enforce_tenant_filter(select(User), User, tenant_b.id)
    result_b = await db_session.execute(query_b)
    users_b = result_b.scalars().all()

    assert len(users_b) == 1
    assert users_b[0].email == "admin@beta.com"
    assert str(users_b[0].tenant_id) == str(tenant_b.id)

    # Verify no cross-tenant leakage
    assert users_a[0].id != users_b[0].id


@pytest.mark.asyncio
async def test_context_tenant_isolation_filter(db_session: AsyncSession, seed_tenants):
    """Verifies that context-aware filter queries strictly using active tenant."""
    tenant_a = seed_tenants["tenant_a"]
    set_current_tenant_context(TenantContext(
        tenant_id=tenant_a.id,
        name=tenant_a.name,
        slug=tenant_a.slug,
    ))

    try:
        query = enforce_current_tenant_filter(select(User), User)
        result = await db_session.execute(query)
        users = result.scalars().all()
        assert len(users) == 1
        assert str(users[0].tenant_id) == str(tenant_a.id)
    finally:
        clear_current_tenant_context()


def test_missing_tenant_context_raises_error():
    """Verifies that executing a tenant-scoped operation without context raises TenantIsolationError."""
    clear_current_tenant_context()
    with pytest.raises(TenantIsolationError):
        enforce_current_tenant_filter(select(User), User)


def test_assert_entity_tenant_prevents_cross_tenant_manipulation(seed_tenants):
    """Verifies that asserting tenant ownership on an entity raises error if tenant IDs mismatch."""
    user_a = seed_tenants["user_a"]
    tenant_b = seed_tenants["tenant_b"]

    with pytest.raises(TenantIsolationError):
        assert_entity_tenant(user_a, tenant_b.id)
