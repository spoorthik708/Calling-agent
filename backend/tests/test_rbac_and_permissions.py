import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_password_hash
from app.models import Tenant, User


@pytest.fixture
async def setup_rbac_test_users(db_session: AsyncSession):
    """Sets up a tenant with Owner, Admin, and Member users."""
    tenant = Tenant(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        name="RBAC Enterprise",
        slug="rbac-enterprise",
        status="active",
        is_active=True,
    )
    db_session.add(tenant)

    owner = User(
        id=uuid.UUID("11111111-0000-0000-0000-000000000001"),
        tenant_id=tenant.id,
        email="owner@rbac.com",
        hashed_password=get_password_hash("Password123456!"),
        role="owner",
        status="active",
        is_active=True,
    )
    admin = User(
        id=uuid.UUID("11111111-0000-0000-0000-000000000002"),
        tenant_id=tenant.id,
        email="admin@rbac.com",
        hashed_password=get_password_hash("Password123456!"),
        role="admin",
        status="active",
        is_active=True,
    )
    member = User(
        id=uuid.UUID("11111111-0000-0000-0000-000000000003"),
        tenant_id=tenant.id,
        email="member@rbac.com",
        hashed_password=get_password_hash("Password123456!"),
        role="member",
        status="active",
        is_active=True,
    )
    db_session.add_all([owner, admin, member])
    await db_session.commit()

    return {"tenant": tenant, "owner": owner, "admin": admin, "member": member}


@pytest.mark.asyncio
async def test_owner_permissions_work(async_client: AsyncClient, setup_rbac_test_users):
    """Test 26: OWNER has full access to tenant updates and user listings."""
    owner = setup_rbac_test_users["owner"]
    token = create_access_token(subject=owner.id, tenant_id=owner.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # OWNER can view tenant profile
    t_res = await async_client.get("/api/v1/tenant", headers=headers)
    assert t_res.status_code == 200

    # OWNER can update tenant profile
    update_res = await async_client.patch(
        "/api/v1/tenant",
        headers=headers,
        json={"name": "RBAC Enterprise Updated"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "RBAC Enterprise Updated"

    # OWNER can view user list
    u_res = await async_client.get("/api/v1/users", headers=headers)
    assert u_res.status_code == 200
    assert len(u_res.json()) == 3


@pytest.mark.asyncio
async def test_admin_permissions_work(async_client: AsyncClient, setup_rbac_test_users):
    """Test 27: ADMIN can read users and view tenant, but cannot update tenant profile."""
    admin = setup_rbac_test_users["admin"]
    token = create_access_token(subject=admin.id, tenant_id=admin.tenant_id, role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    # ADMIN can view tenant profile
    t_res = await async_client.get("/api/v1/tenant", headers=headers)
    assert t_res.status_code == 200

    # ADMIN can read users
    u_res = await async_client.get("/api/v1/users", headers=headers)
    assert u_res.status_code == 200


@pytest.mark.asyncio
async def test_admin_cannot_perform_owner_only_operations(async_client: AsyncClient, setup_rbac_test_users):
    """Test 30: ADMIN receives 403 when attempting OWNER-only operations (e.g. PATCH /tenant)."""
    admin = setup_rbac_test_users["admin"]
    token = create_access_token(subject=admin.id, tenant_id=admin.tenant_id, role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    # ADMIN cannot update tenant configuration
    res = await async_client.patch(
        "/api/v1/tenant",
        headers=headers,
        json={"name": "Hacked Tenant Name"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_access_admin_endpoints(async_client: AsyncClient, setup_rbac_test_users):
    """
    Tests 28, 29, 31:
    - MEMBER can access self profile
    - MEMBER cannot access /api/v1/users list
    - MEMBER cannot patch /api/v1/tenant
    """
    member = setup_rbac_test_users["member"]
    token = create_access_token(subject=member.id, tenant_id=member.tenant_id, role="member")
    headers = {"Authorization": f"Bearer {token}"}

    # Self profile works
    me_res = await async_client.get("/api/v1/users/me", headers=headers)
    assert me_res.status_code == 200

    # User listing is forbidden for MEMBER
    list_res = await async_client.get("/api/v1/users", headers=headers)
    assert list_res.status_code == 403

    # Tenant update is forbidden for MEMBER
    patch_res = await async_client.patch(
        "/api/v1/tenant",
        headers=headers,
        json={"name": "Member Attempted Name"},
    )
    assert patch_res.status_code == 403


@pytest.mark.asyncio
async def test_owner_cannot_be_disabled_by_admin(async_client: AsyncClient, setup_rbac_test_users):
    """
    Test 32 (SECTION 16 OWNER PROTECTION):
    ADMIN cannot disable, modify, or demote an OWNER.
    """
    admin = setup_rbac_test_users["admin"]
    owner = setup_rbac_test_users["owner"]
    token = create_access_token(subject=admin.id, tenant_id=admin.tenant_id, role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    # Admin tries to suspend the Owner
    res = await async_client.patch(
        f"/api/v1/users/{owner.id}",
        headers=headers,
        json={"status": "suspended"},
    )
    assert res.status_code == 403
    assert "cannot modify users with equal or higher" in res.json()["detail"].lower()


# ==============================================================================
# SEC-04: OWNER SELF-DEACTIVATION PROTECTION
# ==============================================================================

@pytest.mark.asyncio
async def test_owner_cannot_deactivate_or_suspend_self(async_client: AsyncClient, setup_rbac_test_users):
    """
    SEC-04 Regression Test:
    A tenant OWNER must not be able to suspend or disable their own account,
    preventing orphaned tenants without an active owner.
    """
    owner = setup_rbac_test_users["owner"]
    token = create_access_token(subject=owner.id, tenant_id=owner.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Owner attempts to suspend their own account -> 400 Bad Request
    res_suspend = await async_client.patch(
        f"/api/v1/users/{owner.id}",
        headers=headers,
        json={"status": "suspended"},
    )
    assert res_suspend.status_code == 400
    assert "cannot disable or suspend their own account" in res_suspend.json()["detail"].lower()

    # 2. Owner attempts to disable their own account -> 400 Bad Request
    res_disable = await async_client.patch(
        f"/api/v1/users/{owner.id}",
        headers=headers,
        json={"status": "disabled"},
    )
    assert res_disable.status_code == 400
    assert "cannot disable or suspend their own account" in res_disable.json()["detail"].lower()

    # 3. Owner CAN still suspend/disable other users (e.g. admin or member)
    admin = setup_rbac_test_users["admin"]
    res_admin_suspend = await async_client.patch(
        f"/api/v1/users/{admin.id}",
        headers=headers,
        json={"status": "suspended"},
    )
    assert res_admin_suspend.status_code == 200
    assert res_admin_suspend.json()["status"] == "suspended"

