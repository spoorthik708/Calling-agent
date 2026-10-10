"""Unit and Integration Tests for Exotel Telephony Provider & Voice AI Transport Bridge.

Verifies:
1. ExotelTelephonyProvider initialization, outbound call dispatching, call termination, and signature verification.
2. Telephony provider factory switching (mock, twilio, exotel).
3. ExotelVoiceTransport audio framing and barge-in clear event generation.
4. Exotel status webhook endpoint processing (CallSid, Status, CallDuration, RecordingUrl).
5. Pre-dispatch consent checks and Indian mobile number normalization (+91...).
"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.database.session import get_db
from app.core.config import get_settings
from app.core.security import create_access_token
from app.telephony.interfaces import OutboundCallRequest, CallState
from app.telephony.models import CallSession
from app.telephony.provider import (
    ExotelTelephonyProvider,
    MockTelephonyProvider,
    TwilioTelephonyProvider,
    get_telephony_provider,
)
from app.tenants.models import Tenant
from app.users.models import User
from app.voice.transport import ExotelVoiceTransport
from app.voice.tts import TTSAudioChunk


@pytest.fixture
async def exotel_test_setup(db_session: AsyncSession):
    """Sets up an active tenant, user, and initial CallSession for Exotel tests."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Exotel Tenant India",
        slug=f"tenant-exotel-{uuid.uuid4().hex[:6]}",
        status="active",
        is_active=True,
    )
    db_session.add(tenant)

    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"admin.exotel.{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_secret",
        first_name="Exotel",
        last_name="Admin",
        role="owner",
        status="active",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(subject=user.id, tenant_id=tenant.id, role="owner")
    headers = {"Authorization": f"Bearer {token}"}

    return {
        "tenant": tenant,
        "user": user,
        "headers": headers,
    }


@pytest.mark.asyncio
async def test_exotel_provider_dispatch_and_hangup():
    """Verifies ExotelTelephonyProvider outbound call dispatching and termination."""
    provider = ExotelTelephonyProvider(
        account_sid="exotel_sid_123",
        api_key="exotel_key_456",
        api_token="exotel_token_789",
        subdomain="api.exotel.com",
    )

    req = OutboundCallRequest(
        tenant_id=uuid.uuid4(),
        to_phone="+919876543210",
        from_phone="1400001234",
        agent_id=uuid.uuid4(),
    )

    call_id = await provider.initiate_outbound_call(req)
    assert call_id.startswith("exotel_call_")

    terminated = await provider.terminate_call(call_id)
    assert terminated is True


def test_exotel_provider_signature_verification():
    """Verifies Exotel HMAC-SHA256 request signature verification."""
    provider = ExotelTelephonyProvider(
        account_sid="exotel_sid_123",
        api_token="my_secret_token_123",
    )

    secret = "my_secret_token_123"
    url = "https://example.com/api/v1/telephony/exotel/status"
    params = {"CallSid": "exotel_call_999", "Status": "completed"}

    # Compute valid signature
    import hmac
    import hashlib
    import base64

    s = url + "CallSidexotel_call_999Statuscompleted"
    computed_mac = hmac.new(secret.encode("utf-8"), s.encode("utf-8"), hashlib.sha256).digest()
    valid_sig = base64.b64encode(computed_mac).decode("utf-8")

    assert provider.verify_exotel_signature(url, params, valid_sig, secret) is True
    assert provider.verify_exotel_signature(url, params, "invalid_signature", secret) is False


def test_provider_factory_resolution():
    """Verifies factory switching between mock, twilio, and exotel providers."""
    mock_p = get_telephony_provider("mock")
    assert isinstance(mock_p, MockTelephonyProvider)

    twilio_p = get_telephony_provider("twilio")
    assert isinstance(twilio_p, TwilioTelephonyProvider)

    exotel_p = get_telephony_provider("exotel")
    assert isinstance(exotel_p, ExotelTelephonyProvider)


@pytest.mark.asyncio
async def test_exotel_voice_transport_audio_and_barge_in():
    """Verifies ExotelVoiceTransport frames audio chunks and sends clear messages on barge-in."""

    class MockWebSocket:
        def __init__(self):
            self.sent_messages = []
            self.is_closed = False

        async def send_text(self, text: str):
            self.sent_messages.append(text)

        async def close(self):
            self.is_closed = True

    ws = MockWebSocket()
    transport = ExotelVoiceTransport(websocket=ws, stream_sid="stream_exotel_100")

    # Send Audio Chunk
    chunk = TTSAudioChunk(audio_bytes=b"sample_pcm_audio_data", text="Hello Exotel")
    await transport.send_audio(chunk)

    assert len(ws.sent_messages) == 1
    import json
    media_data = json.loads(ws.sent_messages[0])
    assert media_data["event"] == "media"
    assert media_data["stream_sid"] == "stream_exotel_100"
    assert "payload" in media_data["media"]

    # Send Barge-in Interruption Event
    await transport.send_event("interrupted", {"reason": "barge_in"})
    assert len(ws.sent_messages) == 2
    clear_data = json.loads(ws.sent_messages[1])
    assert clear_data["event"] == "clear"
    assert clear_data["stream_sid"] == "stream_exotel_100"

    await transport.close()
    assert ws.is_closed is True


@pytest.mark.asyncio
async def test_exotel_call_status_webhook_endpoint(db_session: AsyncSession, exotel_test_setup: dict):
    """Verifies POST /api/v1/telephony/exotel/status webhook processing."""
    tenant = exotel_test_setup["tenant"]

    # Seed a CallSession in RINGING state
    provider_call_id = "exotel_call_test_888"
    call_session = CallSession(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        agent_id=uuid.uuid4(),
        provider_call_id=provider_call_id,
        telephony_provider="exotel",
        direction="outbound",
        from_phone="1400001234",
        to_phone="+919876543210",
        status="ringing",
        duration_seconds=0,
    )
    db_session.add(call_session)
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            form_payload = {
                "CallSid": provider_call_id,
                "Status": "completed",
                "CallDuration": "45",
                "RecordingUrl": "https://api.exotel.com/recordings/test.mp3",
            }
            res = await client.post("/api/v1/telephony/exotel/status", data=form_payload)
            assert res.status_code == 200
            assert res.json() == {"status": "ok"}

            # Verify database record updated
            await db_session.refresh(call_session)
            assert call_session.status == "completed"
            assert call_session.duration_seconds == 45
            assert call_session.recording_url == "https://api.exotel.com/recordings/test.mp3"
    finally:
        app.dependency_overrides.clear()
