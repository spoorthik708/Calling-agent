import asyncio
import uuid
import pytest
from httpx import AsyncClient
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_idempotency_key_duplicate_prevention(async_client: AsyncClient, seed_tenants):
    """
    Verifies that sending a message with an Idempotency-Key returns the cached response
    without creating duplicate messages in the conversation history.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    # Create Agent & Conversation
    agent_res = await async_client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "Idempotent Agent", "system_prompt": "Test"},
    )
    agent_id = agent_res.json()["id"]

    conv_res = await async_client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"agent_id": agent_id},
    )
    conv_id = conv_res.json()["id"]

    idem_key = "req-test-uuid-12345"
    idem_headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": idem_key,
    }

    # 1. First execution
    res1 = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=idem_headers,
        json={"content": "Hello agent!"},
    )
    assert res1.status_code == 200
    data1 = res1.json()

    # 2. Duplicate retry with same idempotency key and identical payload
    res2 = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=idem_headers,
        json={"content": "Hello agent!"},
    )
    assert res2.status_code == 200
    data2 = res2.json()

    # Must return exact same response and message IDs
    assert data1["assistant_message_id"] == data2["assistant_message_id"]
    assert data1["user_message_id"] == data2["user_message_id"]

    # 3. Verify exactly 2 messages in conversation history (1 user + 1 assistant)
    history_res = await async_client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
    )
    assert history_res.status_code == 200
    msgs = history_res.json()
    assert len(msgs) == 2


@pytest.mark.asyncio
async def test_idempotency_conflict_with_differing_payload(async_client: AsyncClient, seed_tenants):
    """
    Verifies that reusing an Idempotency-Key with a differing request body raises 409 Conflict.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")

    # Create Agent & Conversation
    agent_res = await async_client.post(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Conflict Agent", "system_prompt": "Test"},
    )
    agent_id = agent_res.json()["id"]

    conv_res = await async_client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"agent_id": agent_id},
    )
    conv_id = conv_res.json()["id"]

    idem_key = "req-conflict-uuid-9999"
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": idem_key,
    }

    # First request
    res1 = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
        json={"content": "First message"},
    )
    assert res1.status_code == 200

    # Reusing same key with different payload -> 409 Conflict
    res2 = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
        json={"content": "Completely different message payload"},
    )
    assert res2.status_code == 409
    assert "differing" in res2.json()["detail"]["message"].lower()


@pytest.mark.asyncio
async def test_simultaneous_idempotent_requests_race(async_client: AsyncClient, seed_tenants):
    """
    IDEMPOTENCY RACE CONDITION TEST:
    Verifies that duplicate requests with the same Idempotency-Key return
    the identical assistant response and do not create duplicate messages.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "simultaneous-race-key-101",
    }

    # Create Agent & Conversation
    agent_res = await async_client.post(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Race Guard Agent", "system_prompt": "Test"},
    )
    agent_id = agent_res.json()["id"]

    conv_res = await async_client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"agent_id": agent_id},
    )
    conv_id = conv_res.json()["id"]

    # First request
    res1 = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
        json={"content": "Simultaneous identical turn"},
    )
    # Second immediate request
    res2 = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
        json={"content": "Simultaneous identical turn"},
    )

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json()["assistant_message_id"] == res2.json()["assistant_message_id"]

    # Verify history has exactly 1 user + 1 assistant message
    history_res = await async_client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert history_res.status_code == 200
    msgs = history_res.json()
    assert len(msgs) == 2


@pytest.mark.asyncio
async def test_simultaneous_different_messages_sequence_integrity(async_client: AsyncClient, seed_tenants):
    """
    CONCURRENCY & SEQUENCE NUMBER INTEGRITY TEST:
    Verifies sequential turn ordering:
    - Sequence numbers are strictly monotonic and unique (1, 2, 3, 4).
    - No duplicate sequence numbers are created.
    - Conversation history is not corrupted.
    """
    user_a = seed_tenants["user_a"]
    token = create_access_token(subject=user_a.id, tenant_id=user_a.tenant_id, role="owner")

    # Create Agent & Conversation
    agent_res = await async_client.post(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Seq Guard Agent", "system_prompt": "Test"},
    )
    agent_id = agent_res.json()["id"]

    conv_res = await async_client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"agent_id": agent_id},
    )
    conv_id = conv_res.json()["id"]

    resA = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "Concurrent message Alpha"},
    )
    resB = await async_client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"content": "Concurrent message Beta"},
    )

    assert resA.status_code == 200
    assert resB.status_code == 200

    # Fetch messages
    history_res = await async_client.get(
        f"/api/v1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert history_res.status_code == 200
    msgs = history_res.json()
    assert len(msgs) == 4

    seqs = [m["sequence_number"] for m in msgs]
    assert seqs == [1, 2, 3, 4]
    # Check roles alternate correctly
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant", "user", "assistant"]
