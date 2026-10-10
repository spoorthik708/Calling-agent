"""Comprehensive Tests for Phase 7 Telephony Routing and Dispatcher.

Validates:
1. Inbound call webhook processing, agent resolution, TwiML payload generation.
2. Outbound call dispatching, tenant authorization, and provider integration.
3. Call status lifecycle transitions (queued -> ringing -> in_progress -> completed/failed).
4. Multi-tenant security & isolation (cross-tenant call access denial).
5. Provider HMAC signature verification.
6. Real-time call analytics & metrics calculation.
"""

from datetime import datetime, timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, User
from app.auth.rbac import Role
from app.core.security import create_access_token
from app.agents.models import Agent, AgentStatus
from app.telephony.interfaces import CallDirection, CallState, OutboundCallRequest
from app.telephony.models import CallSession
from app.telephony.provider import MockTelephonyProvider
from app.telephony.service import TelephonyService


@pytest.fixture
async def telephony_setup(db_session: AsyncSession):
    tenant_a = Tenant(id=uuid.uuid4(), name="Alpha Corp", slug="alpha-corp", is_active=True)
    tenant_b = Tenant(id=uuid.uuid4(), name="Beta Corp", slug="beta-corp", is_active=True)
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()

    user_a = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email="manager@alpha.com",
        hashed_password="pw",
        role=Role.ADMIN.value,
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        email="manager@beta.com",
        hashed_password="pw",
        role=Role.ADMIN.value,
        is_active=True,
    )
    db_session.add_all([user_a, user_b])

    agent_a = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        name="Alpha Telephony Agent",
        system_prompt="You are a helpful phone representative.",
        status=AgentStatus.ACTIVE.value,
        llm_provider="mock",
        llm_model="mock-model",
    )
    agent_b = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        name="Beta Telephony Agent",
        system_prompt="You are a helpful phone representative.",
        status=AgentStatus.ACTIVE.value,
        llm_provider="mock",
        llm_model="mock-model",
    )
    db_session.add_all([agent_a, agent_b])
    await db_session.commit()

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
        "agent_a": agent_a,
        "agent_b": agent_b,
    }


@pytest.mark.asyncio
async def test_inbound_call_webhook_flow(async_client: AsyncClient, telephony_setup):
    """Verifies that incoming call webhook creates conversation, voice session, and returns TwiML."""
    tenant = telephony_setup["tenant_a"]
    agent = telephony_setup["agent_a"]

    headers = {"X-Tenant-ID": str(tenant.id)}
    payload = {
        "provider_call_id": f"CA_test_inbound_{uuid.uuid4().hex[:8]}",
        "from_phone": "+15550199",
        "to_phone": "+18005550100",
        "agent_id": str(agent.id),
        "metadata": {"source": "inbound_ad"},
    }

    res = await async_client.post("/api/v1/telephony/inbound/webhook", headers=headers, json=payload)
    assert res.status_code == 200
    data = res.json()

    assert "call_session_id" in data
    assert "voice_session_id" in data
    assert "twiml" in data
    assert "Response" in data["twiml"]
    assert "Stream" in data["twiml"]
    assert data["status"] == CallState.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_outbound_call_dispatch_flow(async_client: AsyncClient, telephony_setup):
    """Verifies dispatching an outbound call creates CallSession in RINGING state."""
    tenant = telephony_setup["tenant_a"]
    user = telephony_setup["user_a"]
    agent = telephony_setup["agent_a"]

    token = create_access_token(subject=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "tenant_id": str(tenant.id),
        "agent_id": str(agent.id),
        "to_phone": "+15550188",
        "from_phone": "+18005550100",
        "custom_parameters": {"campaign": "outreach_q4"},
    }

    res = await async_client.post("/api/v1/telephony/outbound", headers=headers, json=payload)
    assert res.status_code == 201
    data = res.json()

    assert data["tenant_id"] == str(tenant.id)
    assert data["agent_id"] == str(agent.id)
    assert data["status"] == CallState.RINGING.value
    assert data["direction"] == CallDirection.OUTBOUND.value
    assert data["provider_call_id"].startswith("CA")


@pytest.mark.asyncio
async def test_call_status_callback_lifecycle(async_client: AsyncClient, telephony_setup, db_session: AsyncSession):
    """Verifies call status callbacks transition state machine and terminate linked voice session."""
    tenant = telephony_setup["tenant_a"]
    agent = telephony_setup["agent_a"]

    provider = MockTelephonyProvider(preset_call_id="CA_callback_test_123")
    service = TelephonyService(db_session, provider=provider)

    req = OutboundCallRequest(
        tenant_id=tenant.id,
        agent_id=agent.id,
        to_phone="+15550177",
        from_phone="+18005550100",
    )
    call = await service.dispatch_outbound_call(req)
    assert call.status == CallState.RINGING.value

    # Update via status webhook endpoint
    res = await async_client.post(
        "/api/v1/telephony/status/webhook",
        json={
            "provider_call_id": "CA_callback_test_123",
            "status": "completed",
            "duration_seconds": 145,
        },
    )
    assert res.status_code == 200

    # Verify updated state
    updated_call = await service.get_call_session(call.id, tenant.id)
    assert updated_call.status == CallState.COMPLETED.value
    assert updated_call.duration_seconds == 145
    assert updated_call.ended_at is not None


@pytest.mark.asyncio
async def test_cross_tenant_call_isolation(async_client: AsyncClient, telephony_setup):
    """Verifies that Tenant B cannot access Tenant A's call session."""
    tenant_a = telephony_setup["tenant_a"]
    user_b = telephony_setup["user_b"]
    agent_a = telephony_setup["agent_a"]

    # Inbound call under Tenant A
    headers_inbound = {"X-Tenant-ID": str(tenant_a.id)}
    payload = {
        "provider_call_id": f"CA_iso_{uuid.uuid4().hex[:8]}",
        "from_phone": "+15550199",
        "to_phone": "+18005550100",
        "agent_id": str(agent_a.id),
    }
    inbound_res = await async_client.post("/api/v1/telephony/inbound/webhook", headers=headers_inbound, json=payload)
    call_id = inbound_res.json()["call_session_id"]

    # User B (Tenant B) tries to read Tenant A's call
    token_b = create_access_token(subject=user_b.id, tenant_id=telephony_setup["tenant_b"].id, role=user_b.role)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    res = await async_client.get(f"/api/v1/telephony/calls/{call_id}", headers=headers_b)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_telephony_analytics(async_client: AsyncClient, telephony_setup):
    """Verifies telephony analytics calculation."""
    tenant = telephony_setup["tenant_a"]
    user = telephony_setup["user_a"]

    token = create_access_token(subject=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    res = await async_client.get("/api/v1/telephony/analytics", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert "total_calls" in data
    assert "inbound_calls" in data
    assert "outbound_calls" in data
    assert "completed_calls" in data
    assert "average_duration_seconds" in data


def test_twilio_signature_verification_algorithm():
    """Verifies authentic Twilio URL + POST-params HMAC-SHA1 signature verification."""
    from app.telephony.provider import TwilioTelephonyProvider

    provider = TwilioTelephonyProvider(auth_token="1234567890abcdef")
    url = "https://mycompany.com/api/v1/telephony/inbound/webhook"
    params = {
        "CallSid": "CA123456789",
        "From": "+15550100",
        "To": "+18005550199",
    }

    # Compute expected signature for test
    import hmac, hashlib, base64
    s = url
    for key in sorted(params.keys()):
        s += f"{key}{params[key]}"
    mac = hmac.new(b"1234567890abcdef", s.encode("utf-8"), hashlib.sha1).digest()
    valid_signature = base64.b64encode(mac).decode("utf-8")

    # Verify valid signature returns True
    assert provider.verify_twilio_signature(url, params, valid_signature, "1234567890abcdef") is True

    # Verify invalid signature returns False
    assert provider.verify_twilio_signature(url, params, "invalid_sig", "1234567890abcdef") is False


@pytest.mark.asyncio
async def test_twilio_voice_transport_media_and_clear_events():
    """Verifies TwilioVoiceTransport formats media frames and clear buffer instructions."""
    from app.voice.transport import TwilioVoiceTransport
    from app.voice.tts import TTSAudioChunk

    class MockWS:
        def __init__(self):
            self.sent_messages = []
        async def send_text(self, text: str):
            self.sent_messages.append(text)

    mock_ws = MockWS()
    transport = TwilioVoiceTransport(mock_ws, stream_sid="MZ12345")

    # 1. Send audio chunk
    chunk = TTSAudioChunk(
        audio_bytes=b"\x00\x01" * 80,
        sample_rate=16000,
        generation_id=1,
        voice_session_id="test_sess",
    )
    await transport.send_audio(chunk)
    assert len(mock_ws.sent_messages) == 1
    assert "media" in mock_ws.sent_messages[0]
    assert "MZ12345" in mock_ws.sent_messages[0]

    # 2. Send barge-in interruption clear event
    await transport.send_event("interrupted", {})
    assert len(mock_ws.sent_messages) == 2
    assert "clear" in mock_ws.sent_messages[1]
    assert "MZ12345" in mock_ws.sent_messages[1]


@pytest.mark.asyncio
async def test_telephony_campaign_crud_flow(async_client: AsyncClient, telephony_setup):
    """Verifies creation, listing, details, and cancellation of calling campaigns."""
    tenant = telephony_setup["tenant_a"]
    user = telephony_setup["user_a"]
    agent = telephony_setup["agent_a"]

    token = create_access_token(subject=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "name": "Q4 Outreach Campaign",
        "agent_id": str(agent.id),
        "from_phone": "+18005550199",
        "target_phones": ["+15550101", "+15550102", "+15550103"],
        "custom_parameters": {"sector": "education"},
    }

    # 1. Create Campaign
    create_res = await async_client.post("/api/v1/telephony/campaigns", headers=headers, json=payload)
    assert create_res.status_code == 201
    camp_data = create_res.json()
    camp_id = camp_data["id"]

    assert camp_data["name"] == "Q4 Outreach Campaign"
    assert camp_data["total_count"] == 3
    assert camp_data["status"] == "running"

    # 2. List Campaigns
    list_res = await async_client.get("/api/v1/telephony/campaigns", headers=headers)
    assert list_res.status_code == 200
    camps = list_res.json()
    assert len(camps) >= 1

    # 3. Cancel Campaign
    cancel_res = await async_client.post(f"/api/v1/telephony/campaigns/{camp_id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"

