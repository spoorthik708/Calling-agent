import pytest
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.core.config import get_settings
from app.knowledge.models import Document, DocumentChunk, DocumentVersion, KnowledgeBase
from app.models import Tenant, User
from app.tools.models import AgentTool, ToolDefinition
from app.voice.audio import AudioEncoding, AudioFrame
from app.voice.pipeline import VoicePipelineService
from app.voice.state import VoiceSessionStatus
from app.voice.transport import MockVoiceTransport


@pytest.fixture
async def full_voice_setup(db_session: AsyncSession, seed_tenants):
    tenant = seed_tenants["tenant_a"]
    user = seed_tenants["user_a"]

    # 1. Create Agent
    agent = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Support Voice Agent",
        system_prompt="You are a professional voice agent. Always answer using verified business facts.",
        llm_provider="mock",
        llm_model="mock-model",
        status=AgentStatus.ACTIVE.value,
        default_language="en",
    )
    db_session.add(agent)

    # 2. Attach Knowledge Base with verified fact
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Support KB",
        description="Support policies",
    )
    db_session.add(kb)
    await db_session.flush()

    from app.agents.models import AgentKnowledgeBase
    akb = AgentKnowledgeBase(
        tenant_id=tenant.id,
        agent_id=agent.id,
        knowledge_base_id=kb.id,
    )
    db_session.add(akb)

    # Document & Chunk
    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        knowledge_base_id=kb.id,
        name="Returns Policy",
        original_filename="policy.txt",
        content_type="text/plain",
        source_type="file",
        status="ready",
    )
    db_session.add(doc)
    await db_session.flush()

    doc_ver = DocumentVersion(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        document_id=doc.id,
        version_number=1,
        content_hash="abc",
    )
    db_session.add(doc_ver)
    await db_session.flush()

    from app.knowledge.models import Embedding

    chunk = DocumentChunk(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        knowledge_base_id=kb.id,
        document_id=doc.id,
        document_version_id=doc_ver.id,
        chunk_index=0,
        content="Returns are accepted within 30 days of purchase for a full refund.",
        content_hash="abc",
    )
    db_session.add(chunk)
    await db_session.flush()

    from app.knowledge.embeddings import MockEmbeddingProvider
    mock_emb_prov = MockEmbeddingProvider()
    doc_vec = await mock_emb_prov.embed_text("Returns are accepted within 30 days of purchase for a full refund.")

    emb = Embedding(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        document_chunk_id=chunk.id,
        vector=doc_vec,
        dimension=1536,
        provider="mock",
        model="mock-embedding-v1",
    )
    db_session.add(emb)

    # 3. Create and assign a Tool
    tool_def = ToolDefinition(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="lookup_customer",
        display_name="Lookup Customer",
        description="Looks up customer status",
        input_schema={"type": "object", "properties": {"customer_id": {"type": "string"}}},
        output_schema={"type": "object"},
        configuration={},
        is_active=True,
    )
    db_session.add(tool_def)
    await db_session.flush()

    agent_tool = AgentTool(
        tenant_id=tenant.id,
        agent_id=agent.id,
        tool_id=tool_def.id,
        enabled=True,
    )
    db_session.add(agent_tool)

    await db_session.commit()
    await db_session.refresh(agent)

    return {"tenant": tenant, "user": user, "agent": agent}


@pytest.mark.asyncio
async def test_voice_turn_orchestration_with_audio_and_stt(db_session: AsyncSession, full_voice_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = full_voice_setup["tenant"]
    agent = full_voice_setup["agent"]
    transport = MockVoiceTransport()

    # Create & Start Session
    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )
    await pipeline.start_session(session.id, tenant.id, transport=transport)

    # Ingest synthetic speech audio frame
    audio_frame = AudioFrame(
        payload=b"\x00" * 3200,
        encoding=AudioEncoding.PCM_S16LE,
        sample_rate=16000,
        channels=1,
    )
    ingest_res = await pipeline.ingest_audio(
        session_id=session.id,
        tenant_id=tenant.id,
        frame=audio_frame,
    )
    assert ingest_res["buffer_bytes"] == 3200

    # Execute Turn
    turn_res = await pipeline.execute_turn(
        session_id=session.id,
        tenant_id=tenant.id,
    )

    assert turn_res["session_id"] == session.id
    assert turn_res["audio_chunks_count"] > 0
    assert turn_res["assistant_text"] != ""
    assert len(transport.sent_chunks) > 0

    # Telemetry verification
    telemetry = turn_res["telemetry"]
    assert "stt_latency_ms" in telemetry
    assert "total_turn_latency_ms" in telemetry

    # Verify session returned to LISTENING status
    reloaded_session = await pipeline.get_session(session.id, tenant.id)
    assert reloaded_session.status == VoiceSessionStatus.LISTENING.value
    assert reloaded_session.turn_count == 1


@pytest.mark.asyncio
async def test_voice_turn_with_verified_rag_knowledge(db_session: AsyncSession, full_voice_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = full_voice_setup["tenant"]
    agent = full_voice_setup["agent"]
    transport = MockVoiceTransport()

    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )
    await pipeline.start_session(session.id, tenant.id, transport=transport)

    # Simulate direct voice turn with question matching knowledge base
    turn_res = await pipeline.execute_turn(
        session_id=session.id,
        tenant_id=tenant.id,
        input_text="Returns are accepted within 30 days of purchase for a full refund.",
    )

    assert "policies have been verified" in turn_res["assistant_text"] or "verified" in turn_res["assistant_text"].lower()
    assert turn_res["audio_chunks_count"] > 0


@pytest.mark.asyncio
async def test_voice_turn_with_tool_execution(db_session: AsyncSession, full_voice_setup):
    pipeline = VoicePipelineService(db_session)
    tenant = full_voice_setup["tenant"]
    agent = full_voice_setup["agent"]
    transport = MockVoiceTransport()

    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )
    await pipeline.start_session(session.id, tenant.id, transport=transport)

    # Question triggering tool lookup
    turn_res = await pipeline.execute_turn(
        session_id=session.id,
        tenant_id=tenant.id,
        input_text="Can you lookup customer status for cust_123?",
    )

    assert turn_res["audio_chunks_count"] > 0
    assert turn_res["assistant_text"] != ""


@pytest.mark.asyncio
async def test_voice_privacy_retention_settings(db_session: AsyncSession, full_voice_setup, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "VOICE_AUDIO_RETENTION_ENABLED", False)
    monkeypatch.setattr(settings, "VOICE_TRANSCRIPT_RETENTION_ENABLED", False)

    pipeline = VoicePipelineService(db_session)
    tenant = full_voice_setup["tenant"]
    agent = full_voice_setup["agent"]
    transport = MockVoiceTransport()

    session = await pipeline.create_session(
        tenant_id=tenant.id,
        agent_id=agent.id,
    )
    await pipeline.start_session(session.id, tenant.id, transport=transport)

    audio_frame = AudioFrame(payload=b"\x00" * 1600)
    await pipeline.ingest_audio(session_id=session.id, tenant_id=tenant.id, frame=audio_frame)

    turn_res = await pipeline.execute_turn(session_id=session.id, tenant_id=tenant.id)

    # When VOICE_TRANSCRIPT_RETENTION_ENABLED is False, transcript is suppressed
    assert turn_res["user_transcript"] is None
