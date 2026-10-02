import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_password_hash
from app.users.models import User


@pytest.mark.asyncio
async def test_create_and_get_agent(async_client: AsyncClient, seed_tenants):
    """
    Verifies that a tenant OWNER can create an agent and fetch its details.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "Customer Support Agent",
        "description": "Handles inbound billing and product FAQs.",
        "system_prompt": "You are a helpful customer support agent for Acme Corp.",
        "default_language": "en",
        "llm_provider": "mock",
        "llm_model": "gpt-4o-mini",
        "temperature": 0.3,
        "max_output_tokens": 512,
        "fallback_message": "I don't have verified knowledge on that topic.",
        "escalation_enabled": True,
    }
    create_res = await async_client.post("/api/v1/agents", headers=headers, json=payload)
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["name"] == "Customer Support Agent"
    assert data["tenant_id"] == str(user_a.tenant_id)
    assert data["status"] == "active"
    assert data["temperature"] == 0.3
    agent_id = data["id"]

    # Get details
    get_res = await async_client.get(f"/api/v1/agents/{agent_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == agent_id
    assert get_res.json()["name"] == "Customer Support Agent"


@pytest.mark.asyncio
async def test_agent_name_uniqueness_per_tenant(async_client: AsyncClient, seed_tenants):
    """
    Verifies that a tenant cannot create two agents with the same name (409 Conflict).
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "Sales Rep Agent",
        "system_prompt": "You are a sales agent.",
    }
    res1 = await async_client.post("/api/v1/agents", headers=headers, json=payload)
    assert res1.status_code == 201

    res2 = await async_client.post("/api/v1/agents", headers=headers, json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_and_archive_agent(async_client: AsyncClient, seed_tenants):
    """
    Verifies updating agent prompts and archiving (soft-delete lifecycle).
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    create_res = await async_client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "Lifecycle Agent", "system_prompt": "Initial prompt."},
    )
    agent_id = create_res.json()["id"]

    # Update
    update_res = await async_client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=headers,
        json={
            "name": "Renamed Lifecycle Agent",
            "temperature": 0.7,
            "status": "inactive",
        },
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Renamed Lifecycle Agent"
    assert update_res.json()["temperature"] == 0.7
    assert update_res.json()["status"] == "inactive"

    # Archive via DELETE endpoint
    del_res = await async_client.delete(f"/api/v1/agents/{agent_id}", headers=headers)
    assert del_res.status_code == 204

    # Verify agent status is archived (not hard deleted, preserving history references)
    get_res = await async_client.get(f"/api/v1/agents/{agent_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_cross_tenant_agent_isolation(async_client: AsyncClient, seed_tenants):
    """
    CRITICAL SECURITY TEST:
    Tenant A must never access, modify, or archive Tenant B's agent.
    """
    user_a = seed_tenants["user_a"]
    user_b = seed_tenants["user_b"]
    token_a = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    token_b = create_access_token(subject=user_b.id, tenant_id=user_b.tenant_id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tenant B creates an agent
    b_res = await async_client.post(
        "/api/v1/agents",
        headers=headers_b,
        json={"name": "Tenant B Proprietary Agent", "system_prompt": "Secret prompt."},
    )
    assert b_res.status_code == 201
    agent_b_id = b_res.json()["id"]

    # 1. Tenant A attempts to GET Tenant B's agent -> 404 Not Found
    a_get_res = await async_client.get(f"/api/v1/agents/{agent_b_id}", headers=headers_a)
    assert a_get_res.status_code == 404

    # 2. Tenant A attempts to PATCH Tenant B's agent -> 404 Not Found
    a_patch_res = await async_client.patch(
        f"/api/v1/agents/{agent_b_id}",
        headers=headers_a,
        json={"name": "Hacked Name"},
    )
    assert a_patch_res.status_code == 404

    # 3. Tenant A attempts to DELETE Tenant B's agent -> 404 Not Found
    a_del_res = await async_client.delete(f"/api/v1/agents/{agent_b_id}", headers=headers_a)
    assert a_del_res.status_code == 404

    # 4. Tenant A list agents must NOT contain Tenant B's agent
    a_list_res = await async_client.get("/api/v1/agents", headers=headers_a)
    assert a_list_res.status_code == 200
    assert all(a["id"] != agent_b_id for a in a_list_res.json())


@pytest.mark.asyncio
async def test_rbac_agent_permissions(async_client: AsyncClient, seed_tenants, db_session: AsyncSession):
    """
    Verifies RBAC enforcement:
    - MEMBER cannot create or delete agents (403 Forbidden).
    - MEMBER can read agents.
    - ADMIN and OWNER can manage agents.
    """
    tenant_a = seed_tenants["tenant_a"]

    member_user = User(
        tenant_id=tenant_a.id,
        email="agent_member@alpha.com",
        hashed_password=get_password_hash("password123456"),
        first_name="Agent",
        last_name="Member",
        role="member",
        status="active",
        is_active=True,
    )
    db_session.add(member_user)
    await db_session.commit()

    member_token = create_access_token(
        subject=member_user.id,
        tenant_id=tenant_a.id,
        role="member",
    )
    member_headers = {"Authorization": f"Bearer {member_token}"}

    # Member attempts to create agent -> 403 Forbidden
    m_create_res = await async_client.post(
        "/api/v1/agents",
        headers=member_headers,
        json={"name": "Member Unauthorized Agent", "system_prompt": "Test"},
    )
    assert m_create_res.status_code == 403
