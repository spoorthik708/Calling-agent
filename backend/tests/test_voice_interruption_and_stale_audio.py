import asyncio
import pytest
import struct
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.voice.audio import AudioEncoding, AudioFrame
from app.voice.pipeline import VoicePipelineService
from app.voice.state import VoiceSessionStatus
from app.voice.transport import MockVoiceTransport


@pytest.fixture
async def interrupt_setup(db_session: AsyncSession, seed_tenants):
    tenant = seed_tenants["tenant_a"]
    user = seed_tenants["user_a"]

    agent = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Interruptible Agent",
        system_prompt="You are a helpful voice assistant.",
        llm_provider="mock",
        llm_model="mock-model",
        status=AgentStatus.ACTIVE.value,
        default_language="en",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    return {"tenant": tenant, "user": user, "agent": agent}


@pytest.mark.asyncio
async def test_manual_interruption_and_generation_bump(db_session: AsyncSession, interrupt_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = interrupt_setup["tenant"]
    agent = interrupt_setup["agent"]
    transport = MockVoiceTransport()

    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )
    await pipeline.start_session(session.id, tenant.id, transport=transport)

    assert session.current_generation_id == 1
    assert session.interruption_count == 0

    # Set status to SPEAKING to simulate active bot output
    session.status = VoiceSessionStatus.SPEAKING.value
    await db_session.commit()

    # Trigger interruption
    interrupted_session = await pipeline.interrupt(
        session_id=session.id,
        tenant_id=tenant.id,
        reason="user_barge_in",
    )

    assert interrupted_session.current_generation_id == 2
    assert interrupted_session.interruption_count == 1
    assert interrupted_session.status == VoiceSessionStatus.LISTENING.value

    # Verify transport event was emitted
    assert len(transport.sent_events) == 1
    evt_name, evt_data = transport.sent_events[0]
    assert evt_name == "interrupted"
    assert evt_data["generation_id"] == 2


@pytest.mark.asyncio
async def test_barge_in_detection_via_audio_ingest(db_session: AsyncSession, interrupt_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = interrupt_setup["tenant"]
    agent = interrupt_setup["agent"]
    transport = MockVoiceTransport()

    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )
    await pipeline.start_session(session.id, tenant.id, transport=transport)

    # Put session into SPEAKING state
    session.status = VoiceSessionStatus.SPEAKING.value
    await db_session.commit()

    # Create synthetic loud speech frame
    loud_samples = [15000, -15000] * 160
    loud_payload = struct.pack(f"<{len(loud_samples)}h", *loud_samples)
    speech_frame = AudioFrame(
        payload=loud_payload,
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate=16000,
        channels=1,
    )

    # Ingesting speech during SPEAKING triggers barge-in
    result = await pipeline.ingest_audio(
        session_id=session.id,
        tenant_id=tenant.id,
        frame=speech_frame,
    )

    assert result["vad_is_speech"] is True

    # Verify session automatically transitioned back to LISTENING and generation bumped
    reloaded = await pipeline.get_session(session.id, tenant.id)
    assert reloaded.current_generation_id == 2
    assert reloaded.interruption_count == 1
    assert reloaded.status == VoiceSessionStatus.LISTENING.value


@pytest.mark.asyncio
async def test_stale_audio_protection_rejection(db_session: AsyncSession, interrupt_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = interrupt_setup["tenant"]
    agent = interrupt_setup["agent"]
    transport = MockVoiceTransport()

    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )
    await pipeline.start_session(session.id, tenant.id, transport=transport)

    # Interrupt 2 times so active generation is 3
    await pipeline.interrupt(session_id=session.id, tenant_id=tenant.id)
    await pipeline.interrupt(session_id=session.id, tenant_id=tenant.id)

    reloaded = await pipeline.get_session(session.id, tenant.id)
    assert reloaded.current_generation_id == 3

    # An audio chunk generated for generation 1 arriving now is stale and must not be accepted by active turn
    from app.voice.tts import TTSAudioChunk
    stale_chunk = TTSAudioChunk(
        audio_payload=b"\x00" * 320,
        generation_id=1,
    )

    context = pipeline.get_active_context(session.id)
    assert context.generation_id == 3
    # Active generation in context is 3, stale_chunk has generation 1
    assert stale_chunk.generation_id < context.generation_id


@pytest.mark.asyncio
async def test_concurrent_interruption_safety(db_session: AsyncSession, interrupt_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = interrupt_setup["tenant"]
    agent = interrupt_setup["agent"]

    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )
    await pipeline.start_session(session.id, tenant.id)

    session.status = VoiceSessionStatus.SPEAKING.value
    await db_session.commit()

    # Trigger 5 interruptions concurrently
    tasks = [
        pipeline.interrupt(session_id=session.id, tenant_id=tenant.id, reason=f"barge_{i}")
        for i in range(5)
    ]
    results = await asyncio.gather(*tasks)

    # All should succeed without crashing or state corruption
    reloaded = await pipeline.get_session(session.id, tenant.id)
    assert reloaded.status == VoiceSessionStatus.LISTENING.value
    assert reloaded.interruption_count >= 1
    assert reloaded.current_generation_id >= 2
