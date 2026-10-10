import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.agents.runtime_service import AgentRuntimeService
from app.conversations.models import Conversation, ConversationChannel, ConversationStatus
from app.core.config import get_settings
from app.core.exceptions import (
    AgentNotFoundError,
    AudioBufferOverflowError,
    ConversationNotFoundError,
    TenantIsolationError,
    VoiceConfigurationError,
    VoiceProviderError,
    VoiceSessionNotFoundError,
    VoiceSessionStateError,
)
from app.core.logging import get_logger
from app.voice.audio import AudioEncoding, AudioFrame, BoundedAudioBuffer
from app.voice.languages import VoiceLanguage, normalize_voice_language
from app.voice.models import VoiceSession
from app.voice.state import VoiceSessionStatus, validate_status_transition
from app.voice.stt import STTProvider, TranscriptSegment, get_stt_provider
from app.voice.telemetry import TurnTelemetry, VoiceSessionTelemetry
from app.voice.text_chunker import TextChunker
from app.voice.transport import MockVoiceTransport, VoiceTransport
from app.voice.tts import TTSAudioChunk, TTSProvider, get_tts_provider
from app.voice.turn_detector import TurnDetector, TurnEvent
from app.voice.vad import VADInterface, VADResult, get_vad_provider

logger = get_logger("yavura.voice.pipeline")


class ActiveSessionContext:
    """
    In-memory state and active components for a live voice session.
    Protects against race conditions and concurrent turn execution via an asyncio Lock.
    """
    def __init__(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        buffer: BoundedAudioBuffer,
        vad: VADInterface,
        turn_detector: TurnDetector,
        stt: STTProvider,
        tts: TTSProvider,
        transport: VoiceTransport,
        generation_id: int = 1,
    ):
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.buffer = buffer
        self.vad = vad
        self.turn_detector = turn_detector
        self.stt = stt
        self.tts = tts
        self.transport = transport
        self.generation_id = generation_id
        self.lock = asyncio.Lock()
        self.current_turn_task: Optional[asyncio.Task] = None
        self.current_synthesizing_task: Optional[asyncio.Task] = None
        self.telemetry = VoiceSessionTelemetry(session_id=str(session_id), tenant_id=str(tenant_id))


class VoicePipelineService:
    """
    Production-grade Voice Pipeline Orchestrator.
    Manages session lifecycle, real-time audio buffering, VAD, turn detection,
    STT transcription, AgentRuntime grounding, LLM streaming, text chunking,
    TTS synthesis, barge-in interruption, stale audio invalidation, and telemetry.
    """

    # In-memory registry for active session contexts (transport, buffer, detectors)
    _active_contexts: Dict[uuid.UUID, ActiveSessionContext] = {}

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def get_session(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> VoiceSession:
        """Retrieves voice session with strict tenant isolation."""
        stmt = select(VoiceSession).where(
            VoiceSession.id == session_id,
            VoiceSession.tenant_id == tenant_id,
        )
        session = (await self.db.execute(stmt)).scalar_one_or_none()
        if not session:
            raise VoiceSessionNotFoundError(
                message=f"Voice session {session_id} not found.",
                details={"session_id": str(session_id)},
            )
        return session

    async def create_session(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        conversation_id: Optional[uuid.UUID] = None,
        input_language: VoiceLanguage = VoiceLanguage.EN,
        output_language: VoiceLanguage = VoiceLanguage.EN,
        stt_provider: Optional[str] = None,
        tts_provider: Optional[str] = None,
        vad_provider: Optional[str] = None,
        voice_id: Optional[str] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> VoiceSession:
        """
        Creates and persists a new voice session in CREATED status.
        Ensures tenant isolation and valid agent/conversation configuration.
        """
        # 1. Verify Agent
        stmt_agent = select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == tenant_id,
        )
        agent = (await self.db.execute(stmt_agent)).scalar_one_or_none()
        if not agent:
            raise AgentNotFoundError(
                message=f"Agent {agent_id} not found for this tenant.",
                details={"agent_id": str(agent_id)},
            )
        if agent.status != AgentStatus.ACTIVE.value:
            raise VoiceConfigurationError(
                message=f"Agent '{agent.name}' is {agent.status}. Only ACTIVE agents can initiate voice sessions.",
                details={"agent_id": str(agent_id), "status": agent.status},
            )

        # 2. Verify or create Conversation
        if conversation_id:
            stmt_conv = select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
            conv = (await self.db.execute(stmt_conv)).scalar_one_or_none()
            if not conv:
                raise ConversationNotFoundError(
                    message=f"Conversation {conversation_id} not found for this tenant.",
                    details={"conversation_id": str(conversation_id)},
                )
            if conv.agent_id != agent_id:
                raise TenantIsolationError(
                    message="Conversation does not belong to the specified agent.",
                    details={"conversation_id": str(conversation_id), "agent_id": str(agent_id)},
                )
        else:
            conv = Conversation(
                tenant_id=tenant_id,
                agent_id=agent_id,
                channel=ConversationChannel.VOICE.value,
                status=ConversationStatus.ACTIVE.value,
                language=input_language.value,
                conversation_metadata=session_metadata or {},
            )
            self.db.add(conv)
            await self.db.flush()
            conversation_id = conv.id

        resolved_stt = stt_provider or self.settings.DEFAULT_STT_PROVIDER
        resolved_tts = tts_provider or self.settings.DEFAULT_TTS_PROVIDER
        resolved_vad = vad_provider or self.settings.DEFAULT_VAD_PROVIDER

        # Instantiate providers to validate configuration early
        _ = get_stt_provider(resolved_stt)
        _ = get_tts_provider(resolved_tts)
        _ = get_vad_provider(resolved_vad)

        now = datetime.now(timezone.utc)
        voice_session = VoiceSession(
            tenant_id=tenant_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            status=VoiceSessionStatus.CREATED.value,
            input_language=input_language.value,
            output_language=output_language.value,
            stt_provider=resolved_stt,
            tts_provider=resolved_tts,
            vad_provider=resolved_vad,
            voice_id=voice_id,
            current_generation_id=1,
            turn_count=0,
            interruption_count=0,
            session_metadata=session_metadata or {},
            created_at=now,
            updated_at=now,
        )
        self.db.add(voice_session)
        await self.db.commit()
        await self.db.refresh(voice_session)

        logger.info(
            "Created voice session %s for tenant %s, agent %s",
            voice_session.id,
            tenant_id,
            agent_id,
        )
        return voice_session

    async def start_session(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        transport: Optional[VoiceTransport] = None,
    ) -> VoiceSession:
        """
        Transitions session from CREATED -> CONNECTING -> ACTIVE -> LISTENING.
        Initializes in-memory audio buffer, detectors, and transport.
        """
        session = await self.get_session(session_id, tenant_id)
        if session.status in (VoiceSessionStatus.ENDED.value, VoiceSessionStatus.FAILED.value):
            raise VoiceSessionStateError(
                message=f"Cannot start session with terminal status '{session.status}'.",
                details={"session_id": str(session_id), "status": session.status},
            )

        validate_status_transition(session.status, VoiceSessionStatus.CONNECTING.value)
        session.status = VoiceSessionStatus.CONNECTING.value
        validate_status_transition(session.status, VoiceSessionStatus.ACTIVE.value)
        session.status = VoiceSessionStatus.ACTIVE.value
        validate_status_transition(session.status, VoiceSessionStatus.LISTENING.value)
        session.status = VoiceSessionStatus.LISTENING.value

        now = datetime.now(timezone.utc)
        session.started_at = now
        session.last_activity_at = now
        session.updated_at = now

        # Initialize in-memory context
        buffer = BoundedAudioBuffer(
            max_chunk_bytes=self.settings.MAX_AUDIO_CHUNK_BYTES,
            max_buffer_bytes=self.settings.MAX_AUDIO_BUFFER_BYTES,
            max_queue_size=self.settings.MAX_AUDIO_QUEUE_SIZE,
        )
        vad = get_vad_provider(session.vad_provider)
        turn_detector = TurnDetector(
            silence_timeout_seconds=self.settings.DEFAULT_SILENCE_TIMEOUT_SECONDS,
            min_speech_duration_seconds=self.settings.DEFAULT_MIN_SPEECH_DURATION_SECONDS,
            max_turn_duration_seconds=self.settings.MAX_TURN_DURATION_SECONDS,
        )
        stt = get_stt_provider(session.stt_provider)
        tts = get_tts_provider(session.tts_provider)
        resolved_transport = transport or MockVoiceTransport()

        context = ActiveSessionContext(
            session_id=session.id,
            tenant_id=tenant_id,
            buffer=buffer,
            vad=vad,
            turn_detector=turn_detector,
            stt=stt,
            tts=tts,
            transport=resolved_transport,
            generation_id=session.current_generation_id,
        )
        self._active_contexts[session.id] = context

        await self.db.commit()
        await self.db.refresh(session)
        logger.info("Voice session %s started and listening.", session.id)
        return session

    def get_active_context(self, session_id: uuid.UUID) -> Optional[ActiveSessionContext]:
        return self._active_contexts.get(session_id)

    async def ingest_audio(
        self,
        *,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        frame: AudioFrame,
    ) -> Dict[str, Any]:
        """
        Receives an audio frame, pushes to bounded buffer, runs VAD and Turn Detection.
        If speech is detected while session is in SPEAKING state, triggers barge-in interruption.
        """
        session = await self.get_session(session_id, tenant_id)
        if session.status in (VoiceSessionStatus.ENDED.value, VoiceSessionStatus.FAILED.value):
            raise VoiceSessionStateError(
                message=f"Cannot ingest audio into session with terminal status '{session.status}'.",
                details={"session_id": str(session_id), "status": session.status},
            )

        context = self._active_contexts.get(session_id)
        if not context:
            raise VoiceSessionStateError(
                message="Voice session is not actively initialized in memory. Please start the session first.",
                details={"session_id": str(session_id)},
            )

        # 1. Run VAD
        vad_result: VADResult = context.vad.is_speech(frame)

        # 2. Check for Barge-in Interruption:
        # If user starts speaking while session is SPEAKING, trigger barge-in immediately
        if vad_result.is_speech and session.status == VoiceSessionStatus.SPEAKING.value:
            logger.info("Barge-in speech detected for session %s during SPEAKING.", session_id)
            await self.interrupt(
                session_id=session_id,
                tenant_id=tenant_id,
                reason="user_barge_in",
            )
            # Re-fetch session status after interruption
            session = await self.get_session(session_id, tenant_id)

        # 3. Buffer Audio
        await context.buffer.push(frame)

        # 4. Run Turn Detection
        turn_event: Optional[TurnEvent] = context.turn_detector.process_frame(frame, vad_result.is_speech)

        session.last_activity_at = datetime.now(timezone.utc)
        await self.db.commit()

        return {
            "session_id": session_id,
            "vad_is_speech": vad_result.is_speech,
            "turn_event": turn_event.value if turn_event else None,
            "buffer_bytes": context.buffer.total_buffered_bytes,
            "queue_size": context.buffer.queue_size,
        }

    async def interrupt(
        self,
        *,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reason: str = "user_barge_in",
    ) -> VoiceSession:
        """
        Barge-in / Interruption handler.
        1. Immediately cancels active TTS synthesis tasks and turn task.
        2. Discards queued audio frames.
        3. Increments current_generation_id (stale audio protection).
        4. Transitions state machine: SPEAKING -> INTERRUPTED -> LISTENING.
        5. Notifies transport and updates telemetry.
        """
        session = await self.get_session(session_id, tenant_id)
        if session.status in (VoiceSessionStatus.ENDED.value, VoiceSessionStatus.FAILED.value):
            raise VoiceSessionStateError(
                message=f"Cannot interrupt a session with terminal status '{session.status}'.",
                details={"session_id": str(session_id), "status": session.status},
            )

        context = self._active_contexts.get(session_id)
        if context:
            # 1. Immediate in-memory invalidation: bump generation and clear buffers
            context.generation_id += 1
            new_gen = context.generation_id
            context.buffer.clear()
            context.turn_detector.reset()

            # 2. Cancel in-flight turn task and synthesis task immediately
            if context.current_turn_task and not context.current_turn_task.done():
                context.current_turn_task.cancel()
                logger.info("Cancelled active turn task for session %s", session_id)
            if context.current_synthesizing_task and not context.current_synthesizing_task.done():
                context.current_synthesizing_task.cancel()
                logger.info("Cancelled active synthesis task for session %s", session_id)

            # 3. Synchronize DB update under lock
            async with context.lock:
                return await self._execute_interrupt(session_id, tenant_id, reason, context, new_gen)

        return await self._execute_interrupt(session_id, tenant_id, reason, None, None)

    async def _execute_interrupt(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reason: str,
        context: Optional[ActiveSessionContext],
        target_gen: Optional[int] = None,
    ) -> VoiceSession:
        session = await self.get_session(session_id, tenant_id)
        old_gen = session.current_generation_id
        new_gen = max(old_gen + 1, target_gen or (old_gen + 1))
        session.current_generation_id = new_gen
        session.interruption_count += 1

        if context:
            context.generation_id = new_gen
            await context.transport.send_event("interrupted", {
                "session_id": str(session_id),
                "generation_id": new_gen,
                "reason": reason,
            })
            context.telemetry.record_interruption()

        # State transition
        if session.status == VoiceSessionStatus.SPEAKING.value:
            validate_status_transition(session.status, VoiceSessionStatus.INTERRUPTED.value)
            session.status = VoiceSessionStatus.INTERRUPTED.value
            validate_status_transition(session.status, VoiceSessionStatus.LISTENING.value)
            session.status = VoiceSessionStatus.LISTENING.value
        elif session.status in (VoiceSessionStatus.PROCESSING.value, VoiceSessionStatus.LISTENING.value):
            session.status = VoiceSessionStatus.LISTENING.value

        session.last_activity_at = datetime.now(timezone.utc)
        session.updated_at = session.last_activity_at
        await self.db.commit()
        await self.db.refresh(session)

        logger.info(
            "Session %s interrupted (gen %d -> %d), transitioned back to LISTENING.",
            session_id,
            old_gen,
            new_gen,
        )
        return session

    async def execute_turn(
        self,
        *,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        input_text: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes a complete voice conversational turn:
        1. Transitions state to PROCESSING.
        2. Transcribes buffered audio via STT if input_text is not provided directly.
        3. Invokes Phase 4 AgentRuntime with verified RAG knowledge and tools.
        4. Transitions state to SPEAKING.
        5. Chunks LLM response into natural spoken phrases.
        6. Streams TTS synthesis with current generation_id.
        7. Sends audio chunks to VoiceTransport, rejecting stale generation IDs.
        8. Transitions state back to LISTENING.
        9. Emits telemetry and handles privacy retention policies.
        """
        session = await self.get_session(session_id, tenant_id)
        if session.status in (VoiceSessionStatus.ENDED.value, VoiceSessionStatus.FAILED.value):
            raise VoiceSessionStateError(
                message=f"Cannot execute turn on a session with terminal status '{session.status}'.",
                details={"session_id": str(session_id), "status": session.status},
            )

        context = self._active_contexts.get(session_id)
        if not context:
            raise VoiceSessionStateError(
                message="Voice session is not actively initialized in memory.",
                details={"session_id": str(session_id)},
            )

        turn_telemetry = TurnTelemetry(
            turn_id=str(uuid.uuid4()),
            generation_id=session.current_generation_id,
        )
        turn_telemetry.start_timer()

        try:
            async with context.lock:
                context.current_turn_task = asyncio.current_task()

                # 1. State: Transition to PROCESSING
                validate_status_transition(session.status, VoiceSessionStatus.PROCESSING.value)
                session.status = VoiceSessionStatus.PROCESSING.value
                session.updated_at = datetime.now(timezone.utc)
                await self.db.commit()

                # 2. STT: Transcribe Audio or use direct text
                user_transcript = input_text
                stt_start = time.perf_counter()

                if not user_transcript:
                    # Collect buffered audio frames
                    frames = context.buffer.drain()
                    if not frames:
                        # No audio to transcribe, return safely to LISTENING
                        session.status = VoiceSessionStatus.LISTENING.value
                        await self.db.commit()
                        return {
                            "session_id": session_id,
                            "turn_id": turn_telemetry.turn_id,
                            "generation_id": session.current_generation_id,
                            "user_transcript": "",
                            "assistant_text": "No audio received.",
                            "audio_chunks_count": 0,
                            "telemetry": turn_telemetry.to_dict(),
                        }

                    # Concatenate payload
                    combined_audio = b"".join(f.payload for f in frames)
                    segment: TranscriptSegment = await context.stt.transcribe_audio(
                        audio_data=combined_audio,
                        encoding=frames[0].encoding,
                        sample_rate=frames[0].sample_rate,
                        language=VoiceLanguage(session.input_language),
                        timeout_seconds=self.settings.STT_TIMEOUT_SECONDS,
                    )
                    user_transcript = segment.text
                    turn_telemetry.record_stt(segment.latency_ms)

                    # Privacy: Drop raw audio immediately if retention is disabled
                    if not self.settings.VOICE_AUDIO_RETENTION_ENABLED:
                        combined_audio = b""
                        frames.clear()
                else:
                    turn_telemetry.record_stt((time.perf_counter() - stt_start) * 1000.0)

                # Check if transcription produced valid text
                cleaned_transcript = (user_transcript or "").strip()
                if not cleaned_transcript:
                    session.status = VoiceSessionStatus.LISTENING.value
                    await self.db.commit()
                    return {
                        "session_id": session_id,
                        "turn_id": turn_telemetry.turn_id,
                        "generation_id": session.current_generation_id,
                        "user_transcript": "",
                        "assistant_text": "Could not understand audio.",
                        "audio_chunks_count": 0,
                        "telemetry": turn_telemetry.to_dict(),
                    }

                # 3. Agent Runtime: Execute Turn
                agent_runtime = AgentRuntimeService(self.db)
                agent_turn_result = await agent_runtime.execute_turn(
                    tenant_id=tenant_id,
                    agent_id=session.agent_id,
                    conversation_id=session.conversation_id,
                    user_message=cleaned_transcript,
                    idempotency_key=idempotency_key,
                )

                if "content" in agent_turn_result:
                    assistant_text = agent_turn_result["content"]
                elif "assistant_message" in agent_turn_result:
                    assistant_text = agent_turn_result["assistant_message"].get("content", "")
                else:
                    assistant_text = str(agent_turn_result)

                llm_latency = agent_turn_result.get("metadata", {}).get(
                    "llm_latency_ms",
                    agent_turn_result.get("assistant_message", {}).get("latency_ms", 10.0)
                    if isinstance(agent_turn_result.get("assistant_message"), dict) else 10.0,
                )
                turn_telemetry.record_llm_first_token(llm_latency)

                # 4. State: Transition to SPEAKING
                validate_status_transition(session.status, VoiceSessionStatus.SPEAKING.value)
                session.status = VoiceSessionStatus.SPEAKING.value
                session.updated_at = datetime.now(timezone.utc)
                await self.db.commit()

                # 5. Text Chunking & Streaming TTS Synthesis
                turn_generation_id = session.current_generation_id
                text_chunker = TextChunker()
                tts_start = time.perf_counter()
                audio_chunks_sent = 0

                # Feed assistant text into chunker to get natural speaking phrases
                clauses = text_chunker.feed(assistant_text)
                clauses.extend(text_chunker.flush())

                for clause in clauses:
                    # Check for interruption before synthesizing next clause
                    if session.current_generation_id != turn_generation_id or context.generation_id != turn_generation_id:
                        logger.info("Turn interrupted during phrase synthesis for session %s", session_id)
                        break

                    async for audio_chunk in context.tts.stream_synthesis(
                        text=clause,
                        language=VoiceLanguage(session.output_language),
                        voice_id=session.voice_id,
                        generation_id=turn_generation_id,
                        voice_session_id=str(session_id),
                        turn_id=turn_telemetry.turn_id,
                        timeout_seconds=self.settings.TTS_TIMEOUT_SECONDS,
                    ):
                        # Stale Audio Protection: verify chunk generation matches active session generation
                        if (
                            int(audio_chunk.generation_id) != session.current_generation_id
                            or int(audio_chunk.generation_id) != context.generation_id
                            or (audio_chunk.voice_session_id and audio_chunk.voice_session_id != str(session_id))
                        ):
                            logger.warning(
                                "Discarding stale audio chunk (chunk_gen=%s, active_gen=%d)",
                                audio_chunk.generation_id,
                                session.current_generation_id,
                            )
                            break

                        if audio_chunks_sent == 0:
                            turn_telemetry.record_tts_first_audio((time.perf_counter() - tts_start) * 1000.0)

                        # Send to transport
                        await context.transport.send_audio(audio_chunk)
                        audio_chunks_sent += 1

                # 6. State: Transition back to LISTENING if not interrupted
                turn_telemetry.stop_timer()
                context.telemetry.record_turn(turn_telemetry)

                if session.status == VoiceSessionStatus.SPEAKING.value and session.current_generation_id == turn_generation_id:
                    validate_status_transition(session.status, VoiceSessionStatus.LISTENING.value)
                    session.status = VoiceSessionStatus.LISTENING.value
                    session.turn_count += 1

                session.last_activity_at = datetime.now(timezone.utc)
                session.updated_at = session.last_activity_at
                await self.db.commit()
                await self.db.refresh(session)

                return {
                    "session_id": session_id,
                    "turn_id": turn_telemetry.turn_id,
                    "generation_id": turn_generation_id,
                    "user_transcript": cleaned_transcript if self.settings.VOICE_TRANSCRIPT_RETENTION_ENABLED else None,
                    "assistant_text": assistant_text,
                    "audio_chunks_count": audio_chunks_sent,
                    "telemetry": turn_telemetry.to_dict(),
                }
        except asyncio.CancelledError:
            logger.info("execute_turn was cancelled by interruption for session %s", session_id)
            return {
                "session_id": session_id,
                "turn_id": turn_telemetry.turn_id,
                "generation_id": session.current_generation_id,
                "user_transcript": "",
                "assistant_text": "",
                "audio_chunks_count": 0,
                "interrupted": True,
                "telemetry": turn_telemetry.to_dict(),
            }
        finally:
            if context and context.current_turn_task == asyncio.current_task():
                context.current_turn_task = None

    async def end_session(
        self,
        *,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reason: str = "normal_completion",
    ) -> VoiceSession:
        """
        Terminates the voice session safely.
        Transitions state machine: ACTIVE/LISTENING/PROCESSING/SPEAKING -> ENDING -> ENDED.
        Cleans up in-memory context and closes transport.
        """
        session = await self.get_session(session_id, tenant_id)
        context = self._active_contexts.pop(session_id, None)

        if context:
            if context.current_turn_task and not context.current_turn_task.done():
                context.current_turn_task.cancel()
            if context.current_synthesizing_task and not context.current_synthesizing_task.done():
                context.current_synthesizing_task.cancel()
            context.buffer.clear()
            await context.transport.close()

        if session.status not in (VoiceSessionStatus.ENDED.value, VoiceSessionStatus.FAILED.value):
            validate_status_transition(session.status, VoiceSessionStatus.ENDING.value)
            session.status = VoiceSessionStatus.ENDING.value
            validate_status_transition(session.status, VoiceSessionStatus.ENDED.value)
            session.status = VoiceSessionStatus.ENDED.value

        now = datetime.now(timezone.utc)
        session.ended_at = now
        session.last_activity_at = now
        session.termination_reason = reason
        session.updated_at = now

        await self.db.commit()
        await self.db.refresh(session)
        logger.info("Voice session %s ended with reason: %s", session_id, reason)
        return session
