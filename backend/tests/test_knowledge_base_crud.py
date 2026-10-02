import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_password_hash
from app.users.models import User


@pytest.mark.asyncio
async def test_create_and_get_knowledge_base(async_client: AsyncClient, seed_tenants):
    """
    Verifies that a tenant OWNER can create a knowledge base and fetch its details.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "Customer Support Knowledge",
        "description": "Standard operating procedures and return policies.",
    }
    create_res = await async_client.post("/api/v1/knowledge-bases", headers=headers, json=payload)
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["name"] == "Customer Support Knowledge"
    assert data["tenant_id"] == str(user_a.tenant_id)
    assert data["status"] == "active"
    kb_id = data["id"]

    # Get details
    get_res = await async_client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == kb_id


@pytest.mark.asyncio
async def test_knowledge_base_name_uniqueness_per_tenant(async_client: AsyncClient, seed_tenants):
    """
    Verifies that a tenant cannot create two knowledge bases with the same name (409 Conflict).
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {"name": "Duplicate Test KB", "description": "First"}
    res1 = await async_client.post("/api/v1/knowledge-bases", headers=headers, json=payload)
    assert res1.status_code == 201

    res2 = await async_client.post("/api/v1/knowledge-bases", headers=headers, json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_and_delete_knowledge_base(async_client: AsyncClient, seed_tenants):
    """
    Verifies that a knowledge base can be updated and deleted.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # Create
    create_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Lifecycle KB", "description": "Original description"},
    )
    kb_id = create_res.json()["id"]

    # Update
    update_res = await async_client.patch(
        f"/api/v1/knowledge-bases/{kb_id}",
        headers=headers,
        json={"name": "Updated Lifecycle KB", "status": "archived"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Updated Lifecycle KB"
    assert update_res.json()["status"] == "archived"

    # Delete
    del_res = await async_client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    assert del_res.status_code == 204

    # Verify 404
    get_res = await async_client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_cross_tenant_knowledge_base_isolation(async_client: AsyncClient, seed_tenants):
    """
    CRITICAL SECURITY TEST:
    Tenant A must never be able to read, update, or delete Tenant B's knowledge base.
    """
    user_a = seed_tenants["user_a"]
    user_b = seed_tenants["user_b"]
    token_a = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    token_b = create_access_token(subject=user_b.id, tenant_id=user_b.tenant_id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tenant B creates a knowledge base
    b_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers_b,
        json={"name": "Tenant B Proprietary KB", "description": "Secret Tenant B data"},
    )
    assert b_res.status_code == 201
    kb_b_id = b_res.json()["id"]

    # 1. Tenant A attempts to GET Tenant B's KB -> 404 Not Found (no info leak)
    a_get_res = await async_client.get(f"/api/v1/knowledge-bases/{kb_b_id}", headers=headers_a)
    assert a_get_res.status_code == 404

    # 2. Tenant A attempts to PATCH Tenant B's KB -> 404 Not Found
    a_patch_res = await async_client.patch(
        f"/api/v1/knowledge-bases/{kb_b_id}",
        headers=headers_a,
        json={"name": "Hacked Name"},
    )
    assert a_patch_res.status_code == 404

    # 3. Tenant A attempts to DELETE Tenant B's KB -> 404 Not Found
    a_del_res = await async_client.delete(f"/api/v1/knowledge-bases/{kb_b_id}", headers=headers_a)
    assert a_del_res.status_code == 404

    # 4. Tenant A's listing must NOT include Tenant B's KB
    a_list_res = await async_client.get("/api/v1/knowledge-bases", headers=headers_a)
    assert a_list_res.status_code == 200
    assert all(kb["id"] != kb_b_id for kb in a_list_res.json())


@pytest.mark.asyncio
async def test_rbac_knowledge_permissions(async_client: AsyncClient, seed_tenants, db_session: AsyncSession):
    """
    Verifies RBAC enforcement:
    - MEMBER cannot create or delete knowledge bases (403 Forbidden).
    - MEMBER can read knowledge bases.
    - ADMIN and OWNER have full management permissions.
    """
    tenant_a = seed_tenants["tenant_a"]

    # Create real member and admin users in the database
    member_user = User(
        tenant_id=tenant_a.id,
        email="member@alpha.com",
        hashed_password=get_password_hash("password123456"),
        first_name="Mary",
        last_name="Member",
        role="member",
        status="active",
        is_active=True,
    )
    admin_user = User(
        tenant_id=tenant_a.id,
        email="admin_sec@alpha.com",
        hashed_password=get_password_hash("password123456"),
        first_name="Alex",
        last_name="Admin",
        role="admin",
        status="active",
        is_active=True,
    )
    db_session.add_all([member_user, admin_user])
    await db_session.commit()

    # Create tokens for different roles in Tenant A
    member_token = create_access_token(
        subject=member_user.id,
        tenant_id=tenant_a.id,
        role="member",
    )
    admin_token = create_access_token(
        subject=admin_user.id,
        tenant_id=tenant_a.id,
        role="admin",
    )
    member_headers = {"Authorization": f"Bearer {member_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Member attempts to create a KB -> 403 Forbidden
    m_create_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=member_headers,
        json={"name": "Member Attempted KB"},
    )
    assert m_create_res.status_code == 403

    # Admin creates KB -> 201 Created
    a_create_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=admin_headers,
        json={"name": "Admin Authorized KB"},
    )
    assert a_create_res.status_code == 201
    kb_id = a_create_res.json()["id"]

    # Member reads KB -> 200 OK
    m_read_res = await async_client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=member_headers)
    assert m_read_res.status_code == 200

    # Member attempts to delete KB -> 403 Forbidden
    m_del_res = await async_client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=member_headers)
    assert m_del_res.status_code == 403
