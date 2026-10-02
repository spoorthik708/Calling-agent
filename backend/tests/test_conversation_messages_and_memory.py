import uuid
import pytest
from httpx import AsyncClient
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_conversation_lifecycle_and_channel_validation(async_client: AsyncClient, seed_tenants):
    """
    Verifies conversation creation, listing, retrieval, and channel validation.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Agent
    agent_res = await async_client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "Chat Agent", "system_prompt": "Help users."},
    )
    agent_id = agent_res.json()["id"]

    # 2. Reject unsupported channels (e.g., voice, sip, twilio are forbidden in Phase 4)
    invalid_chan_res = await async_client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"agent_id": agent_id, "channel": "voice"},
    )
    assert invalid_chan_res.status_code == 422

    # 3. Create valid text conversation
    conv_res = await async_client.post(
        "/api/v1/conversations",
        headers=headers,
        json={
            "agent_id": agent_id,
            "channel": "text",
            "language": "en",
            "external_user_id": "customer_123",
        },
    )
    assert conv_res.status_code == 201
    conv_data = conv_res.json()
    assert conv_data["agent_id"] == agent_id
    assert conv_data["channel"] == "text"
    assert conv_data["status"] == "active"
    conv_id = conv_data["id"]

    # 4. Get conversation
    get_res = await async_client.get(f"/api/v1/conversations/{conv_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == conv_id

    # 5. List conversations
    list_res = await async_client.get(f"/api/v1/conversations?agent_id={agent_id}", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1


@pytest.mark.asyncio
async def test_cannot_create_conversation_for_inactive_agent(async_client: AsyncClient, seed_tenants):
    """
    Verifies that conversations cannot be initiated with inactive or archived agents.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # Create agent
    agent_res = await async_client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "Inactive Agent", "system_prompt": "Test"},
    )
    agent_id = agent_res.json()["id"]

    # Deactivate agent
    await async_client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=headers,
        json={"status": "inactive"},
    )

    # Attempt to create conversation -> 400 Bad Request
    conv_res = await async_client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"agent_id": agent_id},
    )
    assert conv_res.status_code == 400
    assert "inactive" in conv_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cross_tenant_conversation_isolation(async_client: AsyncClient, seed_tenants):
    """
    CRITICAL SECURITY TEST:
    Tenant A must never view, list, or send messages to Tenant B's conversation.
    """
    user_a = seed_tenants["user_a"]
    user_b = seed_tenants["user_b"]
    token_a = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    token_b = create_access_token(subject=user_b.id, tenant_id=user_b.tenant_id, role="owner")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tenant B creates Agent & Conversation
    agent_b = await async_client.post(
        "/api/v1/agents",
        headers=headers_b,
        json={"name": "Agent B", "system_prompt": "Prompt B"},
    )
    agent_b_id = agent_b.json()["id"]

    conv_b = await async_client.post(
        "/api/v1/conversations",
        headers=headers_b,
        json={"agent_id": agent_b_id},
    )
    conv_b_id = conv_b.json()["id"]

    # 1. Tenant A attempts to GET Tenant B's conversation -> 404
    a_get = await async_client.get(f"/api/v1/conversations/{conv_b_id}", headers=headers_a)
    assert a_get.status_code == 404

    # 2. Tenant A attempts to GET messages -> 404
    a_get_msg = await async_client.get(f"/api/v1/conversations/{conv_b_id}/messages", headers=headers_a)
    assert a_get_msg.status_code == 404

    # 3. Tenant A attempts to POST message -> 404
    a_post_msg = await async_client.post(
        f"/api/v1/conversations/{conv_b_id}/messages",
        headers=headers_a,
        json={"content": "Malicious probe"},
    )
    assert a_post_msg.status_code == 404
