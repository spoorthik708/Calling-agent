import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.conversations.models import Conversation, ConversationChannel, ConversationStatus
from app.core.exceptions import (
    AgentNotFoundError,
    VoiceConfigurationError,
    VoiceSessionNotFoundError,
    VoiceSessionStateError,
)
from app.models import Tenant, User
from app.voice.models import VoiceSession
from app.voice.pipeline import VoicePipelineService
from app.voice.state import VoiceSessionStatus, validate_status_transition


@pytest.fixture
async def voice_setup(db_session: AsyncSession, seed_tenants):
    tenant_a = seed_tenants["tenant_a"]
    user_a = seed_tenants["user_a"]

    agent = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        name="Voice Test Agent",
        system_prompt="You are a helpful customer service voice assistant.",
        llm_provider="mock",
        llm_model="mock-model",
        status=AgentStatus.ACTIVE.value,
        default_language="en",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    return {"tenant": tenant_a, "user": user_a, "agent": agent}


@pytest.mark.asyncio
async def test_voice_session_creation_and_defaults(db_session: AsyncSession, voice_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = voice_setup["tenant"]
    agent = voice_setup["agent"]

    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )

    assert session.id is not None
    assert session.tenant_id == tenant.id
    assert session.agent_id == agent.id
    assert session.conversation_id is not None
    assert session.status == VoiceSessionStatus.CREATED.value
    assert session.input_language == "en"
    assert session.output_language == "en"
    assert session.current_generation_id == 1
    assert session.turn_count == 0
    assert session.interruption_count == 0

    # Verify conversation created with VOICE channel
    conv = (
        await db_session.execute(
            select(Conversation).where(Conversation.id == session.conversation_id)
        )
    ).scalar_one()
    assert conv.channel == ConversationChannel.VOICE.value
    assert conv.tenant_id == tenant.id


@pytest.mark.asyncio
async def test_voice_session_inactive_agent_rejected(db_session: AsyncSession, voice_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = voice_setup["tenant"]

    inactive_agent = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Inactive Voice Agent",
        system_prompt="Prompt",
        llm_provider="mock",
        llm_model="mock-model",
        status=AgentStatus.INACTIVE.value,
        default_language="en",
    )
    db_session.add(inactive_agent)
    await db_session.commit()

    with pytest.raises(VoiceConfigurationError):
        await pipeline.create_session(
            tenant_id=tenant.id,
            agent_id=inactive_agent.id,
        )


@pytest.mark.asyncio
async def test_voice_session_state_machine_valid_transitions(db_session: AsyncSession, voice_setup):
    # Test valid transitions
    assert validate_status_transition("created", "connecting") is True
    assert validate_status_transition("connecting", "active") is True
    assert validate_status_transition("active", "listening") is True
    assert validate_status_transition("listening", "processing") is True
    assert validate_status_transition("processing", "speaking") is True
    assert validate_status_transition("speaking", "listening") is True
    assert validate_status_transition("speaking", "interrupted") is True
    assert validate_status_transition("interrupted", "listening") is True
    assert validate_status_transition("listening", "ending") is True
    assert validate_status_transition("ending", "ended") is True
    assert validate_status_transition("speaking", "failed") is True


@pytest.mark.asyncio
async def test_voice_session_state_machine_invalid_transitions():
    # Direct jump from created to speaking must be rejected
    with pytest.raises(VoiceSessionStateError):
        validate_status_transition("created", "speaking")

    # From ended to listening must be rejected
    with pytest.raises(VoiceSessionStateError):
        validate_status_transition("ended", "listening")

    # From ended to created must be rejected
    with pytest.raises(VoiceSessionStateError):
        validate_status_transition("ended", "created")


@pytest.mark.asyncio
async def test_voice_session_start_and_end_lifecycle(db_session: AsyncSession, voice_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = voice_setup["tenant"]
    agent = voice_setup["agent"]

    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )

    started_session = await pipeline.start_session(session.id, tenant.id)
    assert started_session.status == VoiceSessionStatus.LISTENING.value
    assert started_session.started_at is not None
    assert pipeline.get_active_context(session.id) is not None

    ended_session = await pipeline.end_session(
        session_id=session.id,
        tenant_id=tenant.id,
        reason="user_hangup",
    )
    assert ended_session.status == VoiceSessionStatus.ENDED.value
    assert ended_session.ended_at is not None
    assert ended_session.termination_reason == "user_hangup"
    assert pipeline.get_active_context(session.id) is None
