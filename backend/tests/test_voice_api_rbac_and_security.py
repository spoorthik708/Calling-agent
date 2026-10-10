import base64
import pytest
import uuid
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.auth.rbac import Permission, Role
from app.core.security import create_access_token
from app.models import Tenant, User


@pytest.fixture
async def voice_api_setup(db_session: AsyncSession, seed_tenants):
    tenant_a = seed_tenants["tenant_a"]
    user_a = seed_tenants["user_a"]
    tenant_b = seed_tenants["tenant_b"]
    user_b = seed_tenants["user_b"]

    token_a = create_access_token(subject=user_a.id, tenant_id=tenant_a.id, role=user_a.role)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    token_b = create_access_token(subject=user_b.id, tenant_id=tenant_b.id, role=user_b.role)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    agent_a = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        name="Agent Alpha Voice",
        system_prompt="Voice prompt",
        llm_provider="mock",
        llm_model="mock-model",
        status=AgentStatus.ACTIVE.value,
        default_language="en",
    )
    db_session.add(agent_a)
    await db_session.commit()
    await db_session.refresh(agent_a)

    return {
        "tenant_a": tenant_a,
        "user_a": user_a,
        "headers_a": headers_a,
        "tenant_b": tenant_b,
        "user_b": user_b,
        "headers_b": headers_b,
        "agent_a": agent_a,
    }


@pytest.mark.asyncio
async def test_voice_session_api_crud_and_tenant_isolation(async_client: AsyncClient, voice_api_setup):
    headers_a = voice_api_setup["headers_a"]
    headers_b = voice_api_setup["headers_b"]
    agent_a = voice_api_setup["agent_a"]

    # 1. Tenant A creates voice session
    payload = {
        "agent_id": str(agent_a.id),
        "input_language": "en",
        "output_language": "en",
    }
    resp = await async_client.post("/api/v1/voice/sessions", json=payload, headers=headers_a)
    assert resp.status_code == 201
    data = resp.json()
    session_id = data["id"]
    assert data["status"] == "created"

    # 2. Tenant A reads session
    get_resp = await async_client.get(f"/api/v1/voice/sessions/{session_id}", headers=headers_a)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == session_id

    # 3. Tenant B attempts to read Tenant A's session -> 404 (strictly isolated)
    b_resp = await async_client.get(f"/api/v1/voice/sessions/{session_id}", headers=headers_b)
    assert b_resp.status_code == 404

    # 4. Tenant B attempts to start Tenant A's session -> 404
    b_start = await async_client.post(f"/api/v1/voice/sessions/{session_id}/start", headers=headers_b)
    assert b_start.status_code == 404


@pytest.mark.asyncio
async def test_voice_session_api_lifecycle(async_client: AsyncClient, voice_api_setup):
    headers_a = voice_api_setup["headers_a"]
    agent_a = voice_api_setup["agent_a"]

    # 1. Create
    resp = await async_client.post(
        "/api/v1/voice/sessions",
        json={"agent_id": str(agent_a.id)},
        headers=headers_a,
    )
    assert resp.status_code == 201
    session_id = resp.json()["id"]

    # 2. Start
    start_resp = await async_client.post(f"/api/v1/voice/sessions/{session_id}/start", headers=headers_a)
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "listening"

    # 3. Audio Ingest
    dummy_audio = base64.b64encode(b"\x00" * 640).decode("utf-8")
    audio_resp = await async_client.post(
        f"/api/v1/voice/sessions/{session_id}/audio",
        json={"audio_base64": dummy_audio},
        headers=headers_a,
    )
    assert audio_resp.status_code == 200
    assert audio_resp.json()["buffer_bytes"] == 640

    # 4. Turn execution
    turn_resp = await async_client.post(
        f"/api/v1/voice/sessions/{session_id}/turn",
        json={"text": "Hello, how are you?"},
        headers=headers_a,
    )
    assert turn_resp.status_code == 200
    assert turn_resp.json()["assistant_text"] != ""

    # 5. Interrupt
    int_resp = await async_client.post(
        f"/api/v1/voice/sessions/{session_id}/interrupt",
        json={"reason": "barge_in"},
        headers=headers_a,
    )
    assert int_resp.status_code == 200
    assert int_resp.json()["new_generation_id"] == 2

    # 6. End
    end_resp = await async_client.post(
        f"/api/v1/voice/sessions/{session_id}/end",
        json={"reason": "finished"},
        headers=headers_a,
    )
    assert end_resp.status_code == 200
    assert end_resp.json()["status"] == "ended"


@pytest.mark.asyncio
async def test_voice_api_rbac_member_permissions(async_client: AsyncClient, db_session: AsyncSession, voice_api_setup):
    tenant_a = voice_api_setup["tenant_a"]
    agent_a = voice_api_setup["agent_a"]

    # Create Member user (has voice:read, voice:create, voice:manage, voice:interrupt, but NOT voice:manage if restricted, or has member role)
    member_user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email="member@alpha.com",
        hashed_password="hash",
        first_name="Member",
        last_name="User",
        role=Role.MEMBER.value,
        status="active",
        is_active=True,
    )
    db_session.add(member_user)
    await db_session.commit()

    token_m = create_access_token(subject=member_user.id, tenant_id=tenant_a.id, role=member_user.role)
    headers_m = {"Authorization": f"Bearer {token_m}"}

    # Member can create voice session
    resp = await async_client.post(
        "/api/v1/voice/sessions",
        json={"agent_id": str(agent_a.id)},
        headers=headers_m,
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_voice_api_rate_limiting(async_client: AsyncClient, voice_api_setup, monkeypatch):
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "VOICE_SESSION_RATE_LIMIT_PER_MINUTE", 2)
    from app.auth.throttling import default_rate_limiter
    default_rate_limiter.clear()

    headers_a = voice_api_setup["headers_a"]
    agent_a = voice_api_setup["agent_a"]
    payload = {"agent_id": str(agent_a.id)}

    # Call 1 & 2 succeed
    r1 = await async_client.post("/api/v1/voice/sessions", json=payload, headers=headers_a)
    assert r1.status_code == 201
    r2 = await async_client.post("/api/v1/voice/sessions", json=payload, headers=headers_a)
    assert r2.status_code == 201

    # Call 3 exceeds limit -> 429
    r3 = await async_client.post("/api/v1/voice/sessions", json=payload, headers=headers_a)
    assert r3.status_code == 429
    assert "rate limit exceeded" in r3.json()["detail"]["message"].lower()
