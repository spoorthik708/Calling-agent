import base64
from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.rbac import Permission
from app.auth.throttling import default_rate_limiter
from app.core.config import get_settings
from app.core.exceptions import (
    AudioBufferOverflowError,
    VoiceConfigurationError,
    VoiceProviderError,
    VoiceRateLimitError,
    VoiceSessionNotFoundError,
    VoiceSessionStateError,
    http_exception_from_domain,
)
from app.core.logging import get_logger
from app.database.session import get_db
from app.users.models import User
from app.voice.audio import AudioFrame
from app.voice.models import VoiceSession
from app.voice.pipeline import VoicePipelineService
from app.voice.schemas import (
    VoiceAudioIngestRequest,
    VoiceAudioIngestResponse,
    VoiceInterruptRequest,
    VoiceInterruptResponse,
    VoiceSessionCreateRequest,
    VoiceSessionEndRequest,
    VoiceSessionListResponse,
    VoiceSessionResponse,
    VoiceTurnRequest,
    VoiceTurnResponse,
)

logger = get_logger("yavura.voice.api")

router = APIRouter(prefix="/voice", tags=["Voice Intelligence Runtime"])


@router.post(
    "/sessions",
    response_model=VoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Voice Session",
    description="Initializes a persistent, channel-agnostic voice session. Requires 'voice:create'.",
)
async def create_voice_session(
    request: VoiceSessionCreateRequest,
    current_user: User = Depends(require_permission(Permission.VOICE_CREATE.value)),
    db: AsyncSession = Depends(get_db),
) -> VoiceSessionResponse:
    settings = get_settings()
    rate_key = f"voice_session:{current_user.tenant_id}"
    if not default_rate_limiter.check_rate_limit(rate_key, settings.VOICE_SESSION_RATE_LIMIT_PER_MINUTE, 60):
        raise http_exception_from_domain(
            VoiceRateLimitError(
                message="Tenant voice session rate limit exceeded.",
                details={"tenant_id": str(current_user.tenant_id)},
            )
        )

    pipeline = VoicePipelineService(db)
    try:
        session = await pipeline.create_session(
            tenant_id=current_user.tenant_id,
            agent_id=request.agent_id,
            conversation_id=request.conversation_id,
            input_language=request.input_language,
            output_language=request.output_language,
            stt_provider=request.stt_provider,
            tts_provider=request.tts_provider,
            vad_provider=request.vad_provider,
            voice_id=request.voice_id,
            session_metadata=request.session_metadata,
        )
        return VoiceSessionResponse.model_validate(session)
    except Exception as exc:
        raise http_exception_from_domain(exc)


@router.get(
    "/sessions",
    response_model=VoiceSessionListResponse,
    summary="List Voice Sessions",
    description="Lists tenant voice sessions with pagination. Requires 'voice:read'.",
)
async def list_voice_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_permission(Permission.VOICE_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> VoiceSessionListResponse:
    stmt = (
        select(VoiceSession)
        .where(VoiceSession.tenant_id == current_user.tenant_id)
        .order_by(desc(VoiceSession.created_at))
        .offset(offset)
        .limit(limit)
    )
    results = (await db.execute(stmt)).scalars().all()

    count_stmt = select(func.count(VoiceSession.id)).where(VoiceSession.tenant_id == current_user.tenant_id)
    total = (await db.execute(count_stmt)).scalar_one()

    return VoiceSessionListResponse(
        items=[VoiceSessionResponse.model_validate(s) for s in results],
        total=total,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=VoiceSessionResponse,
    summary="Get Voice Session",
    description="Retrieves voice session details. Requires 'voice:read'.",
)
async def get_voice_session(
    session_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.VOICE_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> VoiceSessionResponse:
    pipeline = VoicePipelineService(db)
    try:
        session = await pipeline.get_session(session_id, current_user.tenant_id)
        return VoiceSessionResponse.model_validate(session)
    except Exception as exc:
        raise http_exception_from_domain(exc)


@router.post(
    "/sessions/{session_id}/start",
    response_model=VoiceSessionResponse,
    summary="Start Voice Session",
    description="Transitions session to ACTIVE and LISTENING state. Requires 'voice:manage'.",
)
async def start_voice_session(
    session_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.VOICE_MANAGE.value)),
    db: AsyncSession = Depends(get_db),
) -> VoiceSessionResponse:
    pipeline = VoicePipelineService(db)
    try:
        session = await pipeline.start_session(session_id, current_user.tenant_id)
        return VoiceSessionResponse.model_validate(session)
    except Exception as exc:
        raise http_exception_from_domain(exc)


@router.post(
    "/sessions/{session_id}/audio",
    response_model=VoiceAudioIngestResponse,
    summary="Ingest Audio Frame",
    description="Buffers audio frame, runs VAD and Turn Detection. Checks for barge-in. Requires 'voice:manage'.",
)
async def ingest_audio_frame(
    session_id: uuid.UUID,
    request: VoiceAudioIngestRequest,
    current_user: User = Depends(require_permission(Permission.VOICE_MANAGE.value)),
    db: AsyncSession = Depends(get_db),
) -> VoiceAudioIngestResponse:
    settings = get_settings()
    rate_key = f"voice_audio:{current_user.tenant_id}"
    if not default_rate_limiter.check_rate_limit(rate_key, settings.VOICE_AUDIO_RATE_LIMIT_PER_MINUTE, 60):
        raise http_exception_from_domain(
            VoiceRateLimitError(
                message="Tenant voice audio ingest rate limit exceeded.",
                details={"tenant_id": str(current_user.tenant_id)},
            )
        )

    try:
        payload = base64.b64decode(request.audio_base64)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid base64 audio payload.",
        )

    # Frame duration estimation: bytes / (sample_rate * channels * (bit_depth / 8))
    bytes_per_sample = request.bit_depth // 8
    total_samples = len(payload) // (request.channels * bytes_per_sample) if bytes_per_sample > 0 else 0
    duration_ms = (total_samples / request.sample_rate) * 1000.0 if request.sample_rate > 0 else 0.0

    frame = AudioFrame(
        payload=payload,
        encoding=request.encoding,
        sample_rate=request.sample_rate,
        channels=request.channels,
        bit_depth=request.bit_depth,
        duration_ms=duration_ms,
    )

    pipeline = VoicePipelineService(db)
    try:
        result = await pipeline.ingest_audio(
            session_id=session_id,
            tenant_id=current_user.tenant_id,
            frame=frame,
        )
        return VoiceAudioIngestResponse(**result)
    except Exception as exc:
        raise http_exception_from_domain(exc)


@router.post(
    "/sessions/{session_id}/turn",
    response_model=VoiceTurnResponse,
    summary="Execute Voice Turn",
    description="Processes buffered audio through STT, AgentRuntime, and TTS streaming. Requires 'voice:manage'.",
)
async def execute_voice_turn(
    session_id: uuid.UUID,
    request: VoiceTurnRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(require_permission(Permission.VOICE_MANAGE.value)),
    db: AsyncSession = Depends(get_db),
) -> VoiceTurnResponse:
    pipeline = VoicePipelineService(db)
    try:
        result = await pipeline.execute_turn(
            session_id=session_id,
            tenant_id=current_user.tenant_id,
            input_text=request.text,
            idempotency_key=idempotency_key or request.idempotency_key,
        )
        return VoiceTurnResponse(**result)
    except Exception as exc:
        logger.exception("execute_voice_turn failed: %s", str(exc))
        raise http_exception_from_domain(exc)


@router.post(
    "/sessions/{session_id}/interrupt",
    response_model=VoiceInterruptResponse,
    summary="Interrupt / Barge-in",
    description="Immediately cancels TTS synthesis, invalidates stale audio generation, and returns to LISTENING. Requires 'voice:interrupt'.",
)
async def interrupt_voice_session(
    session_id: uuid.UUID,
    request: VoiceInterruptRequest,
    current_user: User = Depends(require_permission(Permission.VOICE_INTERRUPT.value)),
    db: AsyncSession = Depends(get_db),
) -> VoiceInterruptResponse:
    pipeline = VoicePipelineService(db)
    try:
        session = await pipeline.get_session(session_id, current_user.tenant_id)
        old_gen = session.current_generation_id
        session = await pipeline.interrupt(
            session_id=session_id,
            tenant_id=current_user.tenant_id,
            reason=request.reason or "user_barge_in",
        )
        return VoiceInterruptResponse(
            session_id=session.id,
            status=session.status,
            interrupted_generation_id=old_gen,
            new_generation_id=session.current_generation_id,
            interruption_count=session.interruption_count,
        )
    except Exception as exc:
        raise http_exception_from_domain(exc)


@router.post(
    "/sessions/{session_id}/end",
    response_model=VoiceSessionResponse,
    summary="End Voice Session",
    description="Terminates the voice session and closes audio transport. Requires 'voice:end'.",
)
async def end_voice_session(
    session_id: uuid.UUID,
    request: VoiceSessionEndRequest,
    current_user: User = Depends(require_permission(Permission.VOICE_END.value)),
    db: AsyncSession = Depends(get_db),
) -> VoiceSessionResponse:
    pipeline = VoicePipelineService(db)
    try:
        session = await pipeline.end_session(
            session_id=session_id,
            tenant_id=current_user.tenant_id,
            reason=request.reason or "normal_completion",
        )
        return VoiceSessionResponse.model_validate(session)
    except Exception as exc:
        raise http_exception_from_domain(exc)
