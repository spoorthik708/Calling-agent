import uuid
import pytest
from httpx import AsyncClient
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_agent_knowledge_base_association_lifecycle(async_client: AsyncClient, seed_tenants):
    """
    Verifies attaching, listing, and detaching knowledge bases to/from an Agent.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Agent
    agent_res = await async_client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "KB Linked Agent", "system_prompt": "Grounding test"},
    )
    assert agent_res.status_code == 201
    agent_id = agent_res.json()["id"]

    # 2. Create Knowledge Base
    kb_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Company Policy KB"},
    )
    assert kb_res.status_code == 201
    kb_id = kb_res.json()["id"]

    # 3. Attach KB to Agent
    attach_res = await async_client.post(
        f"/api/v1/agents/{agent_id}/knowledge-bases/{kb_id}",
        headers=headers,
    )
    assert attach_res.status_code == 201
    assert attach_res.json()["agent_id"] == agent_id
    assert attach_res.json()["knowledge_base_id"] == kb_id

    # 4. Duplicate attachment returns existing association safely (idempotent)
    dup_attach = await async_client.post(
        f"/api/v1/agents/{agent_id}/knowledge-bases/{kb_id}",
        headers=headers,
    )
    assert dup_attach.status_code == 201

    # 5. List attached KBs
    list_res = await async_client.get(
        f"/api/v1/agents/{agent_id}/knowledge-bases",
        headers=headers,
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["knowledge_base_id"] == kb_id

    # 6. Detach KB
    detach_res = await async_client.delete(
        f"/api/v1/agents/{agent_id}/knowledge-bases/{kb_id}",
        headers=headers,
    )
    assert detach_res.status_code == 204

    # 7. List again -> 0
    list_res2 = await async_client.get(
        f"/api/v1/agents/{agent_id}/knowledge-bases",
        headers=headers,
    )
    assert list_res2.status_code == 200
    assert len(list_res2.json()) == 0


@pytest.mark.asyncio
async def test_cross_tenant_knowledge_base_association_prevention(async_client: AsyncClient, seed_tenants):
    """
    CRITICAL SECURITY TEST:
    Tenant A must never attach Tenant B's knowledge base to Tenant A's agent,
    nor attach Tenant A's KB to Tenant B's agent.
    """
    user_a = seed_tenants["user_a"]
    user_b = seed_tenants["user_b"]
    token_a = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    token_b = create_access_token(subject=user_b.id, tenant_id=user_b.tenant_id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tenant A creates Agent
    agent_a_res = await async_client.post(
        "/api/v1/agents",
        headers=headers_a,
        json={"name": "Agent Tenant A", "system_prompt": "Test"},
    )
    agent_a_id = agent_a_res.json()["id"]

    # Tenant B creates KB
    kb_b_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers_b,
        json={"name": "Proprietary KB Tenant B"},
    )
    kb_b_id = kb_b_res.json()["id"]

    # Tenant A attempts to attach Tenant B's KB to Tenant A's Agent -> 404
    cross_attach = await async_client.post(
        f"/api/v1/agents/{agent_a_id}/knowledge-bases/{kb_b_id}",
        headers=headers_a,
    )
    assert cross_attach.status_code == 404

    # Tenant B attempts to attach Tenant B's KB to Tenant A's Agent -> 404
    cross_attach_2 = await async_client.post(
        f"/api/v1/agents/{agent_a_id}/knowledge-bases/{kb_b_id}",
        headers=headers_b,
    )
    assert cross_attach_2.status_code == 404
