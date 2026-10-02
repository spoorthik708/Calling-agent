import uuid
import pytest
from httpx import AsyncClient
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_agent_runtime_grounded_response_with_citations(async_client: AsyncClient, seed_tenants):
    """
    Verifies that:
    1. An agent with an attached knowledge base retrieves relevant facts.
    2. The assistant response includes structured citations with chunk and document provenance.
    3. User and assistant messages are correctly persisted with sequential sequence numbers.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Knowledge Base and Ingest Document
    kb_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Billing Policies KB"},
    )
    assert kb_res.status_code == 201
    kb_id = kb_res.json()["id"]

    ingest_res = await async_client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/text",
        headers=headers,
        json={
            "name": "Refund Policy",
            "content": "All enterprise plans are eligible for a 100% money-back refund guarantee within 30 days of purchase.",
        },
    )
    assert ingest_res.status_code == 201

    # 2. Create Agent and attach the KB
    agent_res = await async_client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "Billing Specialist",
            "system_prompt": "You are a helpful billing specialist. Ground answers in verified facts.",
            "llm_provider": "mock",
            "llm_model": "gpt-4o-mini",
        },
    )
    assert agent_res.status_code == 201
    agent_id = agent_res.json()["id"]

    attach_res = await async_client.post(
        f"/api/v1/agents/{agent_id}/knowledge-bases/{kb_id}",
        headers=headers,
    )
    assert attach_res.status_code == 201

    # 3. Create Conversation
    conv_res = await async_client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"agent_id": agent_id},
    )
    assert conv_res.status_code == 201
    conv_id = conv_res.json()["id"]

    # 4. Execute turn
    msg_res = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
        json={"content": "What is the refund guarantee policy for enterprise plans?"},
    )
    assert msg_res.status_code == 200
    turn_data = msg_res.json()
    assert turn_data["user_sequence_number"] == 1
    assert turn_data["assistant_sequence_number"] == 2
    assert "verified" in turn_data["content"].lower()
    assert len(turn_data["citations"]) >= 1
    citation = turn_data["citations"][0]
    assert citation["document_name"] == "Refund Policy"
    assert citation["knowledge_base_id"] == kb_id
    assert citation["similarity_score"] > 0.0

    # 5. Verify persisted messages
    history_res = await async_client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
    )
    assert history_res.status_code == 200
    msgs = history_res.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["sequence_number"] == 1
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["sequence_number"] == 2
    assert msgs[1]["citations"] is not None


@pytest.mark.asyncio
async def test_agent_runtime_unattached_kb_is_not_searched(async_client: AsyncClient, seed_tenants):
    """
    CRITICAL GROUNDING BOUNDARY:
    An agent must NEVER search an unattached knowledge base, even if it belongs to the same tenant.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create KB and Ingest Document
    kb_res = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Unattached Secret KB"},
    )
    kb_id = kb_res.json()["id"]

    await async_client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents/text",
        headers=headers,
        json={
            "name": "Secret Roadmap",
            "content": "Secret Project Apollo launches on December 15.",
        },
    )

    # 2. Create Agent with NO attached knowledge bases
    agent_res = await async_client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "Unlinked Agent",
            "system_prompt": "Answer general questions.",
            "llm_provider": "mock",
        },
    )
    agent_id = agent_res.json()["id"]

    # 3. Create Conversation
    conv_res = await async_client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"agent_id": agent_id},
    )
    conv_id = conv_res.json()["id"]

    # 4. Execute turn
    msg_res = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
        json={"content": "When does Project Apollo launch?"},
    )
    assert msg_res.status_code == 200
    turn_data = msg_res.json()
    # Zero citations because KB is not attached
    assert len(turn_data["citations"]) == 0
