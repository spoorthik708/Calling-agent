"""Telephony API Endpoints for Phase 7.

Handles inbound call webhooks, outbound call dispatching, status callbacks,
call details retrieval, call history filtering, and real-time call analytics.
"""

from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_permission
from app.auth.rbac import Permission
from app.database.session import get_db
from app.models import User
from app.telephony.interfaces import InboundCallPayload, OutboundCallRequest, CallState
from app.telephony.schemas import (
    CallSessionResponse,
    InboundCallWebhookRequest,
    OutboundCallDispatchResponse,
    StatusWebhookPayload,
    TelephonyAnalyticsResponse,
)
from app.telephony.service import TelephonyService

router = APIRouter(prefix="/telephony", tags=["Telephony"])


@router.post(
    "/inbound/webhook",
    status_code=status.HTTP_200_OK,
    summary="Inbound Phone Call Webhook",
    description="Public webhook endpoint triggered by PSTN/SIP provider for incoming calls.",
)
async def inbound_call_webhook(
    payload: InboundCallWebhookRequest,
    x_tenant_id: uuid.UUID = Header(..., alias="X-Tenant-ID", description="Tenant ID header for multi-tenant routing"),
    x_signature: Optional[str] = Header(None, alias="X-Twilio-Signature", description="Provider HMAC signature"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    service = TelephonyService(db)

    inbound_payload = InboundCallPayload(
        provider_call_id=payload.provider_call_id,
        from_phone=payload.from_phone,
        to_phone=payload.to_phone,
        tenant_id=x_tenant_id,
        metadata=payload.metadata,
    )

    result = await service.handle_inbound_call(
        payload=inbound_payload,
        agent_id=payload.agent_id,
        tenant_id=x_tenant_id,
    )
    return result


@router.post(
    "/outbound",
    response_model=OutboundCallDispatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Dispatch Outbound Phone Call",
    description="Initiates an outbound phone call for an active agent under strict tenant isolation.",
)
async def dispatch_outbound_call(
    request: OutboundCallRequest,
    current_user: User = Depends(require_permission(Permission.TELEPHONY_DISPATCH.value)),
    db: AsyncSession = Depends(get_db),
) -> OutboundCallDispatchResponse:
    # Ensure tenant matches token context
    if request.tenant_id != current_user.tenant_id and current_user.role != Role.OWNER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot dispatch call for another tenant.")

    service = TelephonyService(db)
    call_session = await service.dispatch_outbound_call(request)

    return OutboundCallDispatchResponse(
        call_id=call_session.id,
        tenant_id=call_session.tenant_id,
        agent_id=call_session.agent_id,
        conversation_id=call_session.conversation_id,
        voice_session_id=call_session.voice_session_id,
        provider_call_id=call_session.provider_call_id,
        direction=call_session.direction,
        from_phone=call_session.from_phone,
        to_phone=call_session.to_phone,
        status=call_session.status,
        created_at=call_session.created_at,
    )


@router.post(
    "/status/webhook",
    status_code=status.HTTP_200_OK,
    summary="Call Status Callback Webhook",
    description="Receives status callbacks from telephony provider to update call lifecycle states.",
)
async def call_status_webhook(
    payload: StatusWebhookPayload,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    service = TelephonyService(db)
    try:
        call_state = CallState(payload.status.lower())
    except ValueError:
        call_state = CallState.FAILED

    await service.update_call_status(
        provider_call_id=payload.provider_call_id,
        new_status=call_state,
        error_message=payload.error_message,
        duration_seconds=payload.duration_seconds,
        recording_url=payload.recording_url,
    )
    return {"status": "ok"}


@router.post(
    "/exotel/status",
    summary="Exotel Call Status Webhook",
    description="Processes real-time Exotel call status webhooks (ringing, answered, completed, busy, failed).",
)
async def exotel_call_status_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    service = TelephonyService(db)
    form_data = await request.form()
    body_params = dict(form_data)

    provider_call_id = body_params.get("CallSid") or body_params.get("Sid") or body_params.get("provider_call_id")
    raw_status = (body_params.get("Status") or body_params.get("status") or "").lower()
    error_msg = body_params.get("DetailedStatus") or body_params.get("error_message")
    duration_str = body_params.get("CallDuration") or body_params.get("duration")

    duration_sec = int(duration_str) if duration_str and str(duration_str).isdigit() else None
    recording_url = body_params.get("RecordingUrl") or body_params.get("recording_url")

    status_map = {
        "completed": CallState.COMPLETED,
        "failed": CallState.FAILED,
        "busy": CallState.BUSY,
        "no-answer": CallState.NO_ANSWER,
        "no_answer": CallState.NO_ANSWER,
        "in-progress": CallState.IN_PROGRESS,
        "in_progress": CallState.IN_PROGRESS,
        "ringing": CallState.RINGING,
    }
    call_state = status_map.get(raw_status, CallState.FAILED)

    if provider_call_id:
        await service.update_call_status(
            provider_call_id=str(provider_call_id),
            new_status=call_state,
            error_message=str(error_msg) if error_msg else None,
            duration_seconds=duration_sec,
            recording_url=str(recording_url) if recording_url else None,
        )

    return {"status": "ok"}


from fastapi import WebSocket, WebSocketDisconnect
from app.voice.pipeline import VoicePipelineService
from app.voice.transport import ExotelVoiceTransport

@router.websocket("/exotel/stream")
async def exotel_voice_stream(
    websocket: WebSocket,
    session_id: uuid.UUID = Query(...),
    tenant_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Exotel Voice AI / AgentStream WebSocket Endpoint.
    Bridges Exotel bidirectional audio stream to VoicePipelineService.
    """
    await websocket.accept()
    transport = ExotelVoiceTransport(websocket)
    pipeline = VoicePipelineService(db)

    try:
        await pipeline.start_session(session_id, tenant_id, transport=transport)
        seq = 0

        while True:
            msg = await websocket.receive()
            if "text" in msg and msg["text"]:
                import json
                try:
                    data = json.loads(msg["text"])
                    event_type = data.get("event")

                    if event_type in ("start", "connected"):
                        stream_sid = data.get("stream_sid") or data.get("streamSid") or data.get("call_sid")
                        if stream_sid:
                            transport.set_stream_sid(stream_sid)
                    elif event_type == "media":
                        payload_b64 = data.get("media", {}).get("payload", "") or data.get("payload", "")
                        if payload_b64:
                            import base64
                            from app.voice.audio import AudioFrame
                            audio_bytes = base64.b64decode(payload_b64)
                            frame = AudioFrame(payload=audio_bytes, sequence=seq)
                            seq += 1
                            await pipeline.ingest_audio(session_id=session_id, tenant_id=tenant_id, frame=frame)
                    elif event_type in ("stop", "disconnect", "end"):
                        await pipeline.end_session(session_id=session_id, tenant_id=tenant_id, reason="exotel_stream_stop")
                        break
                except Exception as parse_err:
                    logger.warning("Error processing Exotel WS event: %s", parse_err)
            elif "bytes" in msg and msg["bytes"]:
                from app.voice.audio import AudioFrame
                frame = AudioFrame(payload=msg["bytes"], sequence=seq)
                seq += 1
                await pipeline.ingest_audio(session_id=session_id, tenant_id=tenant_id, frame=frame)

    except WebSocketDisconnect:
        logger.info("Exotel WS disconnected for session %s", session_id)
        try:
            await pipeline.end_session(session_id=session_id, tenant_id=tenant_id, reason="ws_disconnect")
        except Exception:
            pass
    except Exception as exc:
        logger.error("Error in exotel_voice_stream: %s", exc, exc_info=True)
        try:
            await pipeline.end_session(session_id=session_id, tenant_id=tenant_id, reason="ws_error")
        except Exception:
            pass


@router.get(
    "/calls/{call_id}",
    response_model=CallSessionResponse,
    summary="Get Call Session Details",
    description="Retrieves a specific CallSession by ID with tenant isolation.",
)
async def get_call_session(
    call_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CallSessionResponse:
    service = TelephonyService(db)
    call = await service.get_call_session(call_id, current_user.tenant_id)
    return CallSessionResponse.model_validate(call, from_attributes=True)


@router.get(
    "/calls",
    response_model=List[CallSessionResponse],
    summary="List Call Sessions",
    description="Lists call sessions for the active tenant with status and direction filters.",
)
async def list_call_sessions(
    status: Optional[str] = Query(None, description="Filter by status (e.g. in_progress, completed, failed)"),
    direction: Optional[str] = Query(None, description="Filter by direction (inbound or outbound)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CallSessionResponse]:
    service = TelephonyService(db)
    calls = await service.list_calls(
        tenant_id=current_user.tenant_id,
        status=status,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    return [CallSessionResponse.model_validate(c, from_attributes=True) for c in calls]


@router.get(
    "/analytics",
    response_model=TelephonyAnalyticsResponse,
    summary="Get Telephony Analytics",
    description="Calculates real-time telephony metrics, total duration, and call completion rates.",
)
async def get_telephony_analytics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelephonyAnalyticsResponse:
    service = TelephonyService(db)
    calls = await service.list_calls(tenant_id=current_user.tenant_id, limit=500)

    total_calls = len(calls)
    inbound = sum(1 for c in calls if c.direction == "inbound")
    outbound = sum(1 for c in calls if c.direction == "outbound")
    completed = sum(1 for c in calls if c.status == "completed")
    failed = sum(1 for c in calls if c.status == "failed")
    busy = sum(1 for c in calls if c.status in ("busy", "no_answer"))
    total_duration = sum(c.duration_seconds for c in calls)
    avg_duration = float(total_duration / total_calls) if total_calls > 0 else 0.0

    return TelephonyAnalyticsResponse(
        total_calls=total_calls,
        inbound_calls=inbound,
        outbound_calls=outbound,
        completed_calls=completed,
        failed_calls=failed,
        busy_calls=busy,
        total_duration_seconds=total_duration,
        average_duration_seconds=round(avg_duration, 2),
    )


from app.telephony.schemas import CampaignCreateRequest, CampaignResponse

@router.post(
    "/campaigns",
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Calling Campaign",
    description="Creates and schedules an automated outbound calling campaign for a target contact list.",
)
async def create_campaign(
    request: CampaignCreateRequest,
    current_user: User = Depends(require_permission(Permission.TELEPHONY_DISPATCH.value)),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    service = TelephonyService(db)
    campaign = await service.create_campaign(
        tenant_id=current_user.tenant_id,
        agent_id=request.agent_id,
        name=request.name,
        from_phone=request.from_phone,
        target_phones=request.target_phones,
        contact_list_id=request.contact_list_id,
        scheduled_at=request.scheduled_at,
        custom_parameters=request.custom_parameters,
    )
    return CampaignResponse.model_validate(campaign, from_attributes=True)


@router.get(
    "/campaigns",
    response_model=List[CampaignResponse],
    summary="List Campaigns",
    description="Lists calling campaigns for the active tenant.",
)
async def list_campaigns(
    status: Optional[str] = Query(None, description="Filter by status (scheduled, running, completed, cancelled)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CampaignResponse]:
    service = TelephonyService(db)
    campaigns = await service.list_campaigns(
        tenant_id=current_user.tenant_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [CampaignResponse.model_validate(c, from_attributes=True) for c in campaigns]


@router.get(
    "/campaigns/{campaign_id}",
    response_model=CampaignResponse,
    summary="Get Campaign Details",
    description="Retrieves a specific calling campaign by ID with tenant isolation.",
)
async def get_campaign(
    campaign_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    service = TelephonyService(db)
    campaign = await service.get_campaign(campaign_id, current_user.tenant_id)
    return CampaignResponse.model_validate(campaign, from_attributes=True)


@router.post(
    "/campaigns/{campaign_id}/cancel",
    response_model=CampaignResponse,
    summary="Cancel Campaign",
    description="Cancels an active or scheduled calling campaign.",
)
async def cancel_campaign(
    campaign_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.TELEPHONY_DISPATCH.value)),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    from app.telephony.worker import CampaignWorkerService
    worker = CampaignWorkerService(db)
    campaign = await worker.cancel_campaign(campaign_id, current_user.tenant_id)
    return CampaignResponse.model_validate(campaign, from_attributes=True)


@router.post(
    "/campaigns/{campaign_id}/pause",
    response_model=CampaignResponse,
    summary="Pause Campaign",
    description="Pauses an active calling campaign.",
)
async def pause_campaign(
    campaign_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.TELEPHONY_DISPATCH.value)),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    from app.telephony.worker import CampaignWorkerService
    worker = CampaignWorkerService(db)
    campaign = await worker.pause_campaign(campaign_id, current_user.tenant_id)
    return CampaignResponse.model_validate(campaign, from_attributes=True)


@router.post(
    "/campaigns/{campaign_id}/resume",
    response_model=CampaignResponse,
    summary="Resume Campaign",
    description="Resumes a paused calling campaign.",
)
async def resume_campaign(
    campaign_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.TELEPHONY_DISPATCH.value)),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    from app.telephony.worker import CampaignWorkerService
    worker = CampaignWorkerService(db)
    campaign = await worker.resume_campaign(campaign_id, current_user.tenant_id)
    return CampaignResponse.model_validate(campaign, from_attributes=True)


@router.post(
    "/campaigns/{campaign_id}/retry-failed",
    response_model=CampaignResponse,
    summary="Retry Failed Campaign Targets",
    description="Resets failed target calls back to queued status for safe retry.",
)
async def retry_failed_campaign_targets(
    campaign_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.TELEPHONY_DISPATCH.value)),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    from app.telephony.worker import CampaignWorkerService
    worker = CampaignWorkerService(db)
    campaign = await worker.retry_failed_targets(campaign_id, current_user.tenant_id)
    return CampaignResponse.model_validate(campaign, from_attributes=True)


from app.telephony.schemas import CampaignTargetResponse
from sqlalchemy import select
from app.telephony.models import CampaignTarget

@router.get(
    "/campaigns/{campaign_id}/targets",
    response_model=List[CampaignTargetResponse],
    summary="List Campaign Targets",
    description="Lists target call records and attempts for a specific campaign with tenant isolation.",
)
async def list_campaign_targets(
    campaign_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CampaignTargetResponse]:
    service = TelephonyService(db)
    await service.get_campaign(campaign_id, current_user.tenant_id)

    stmt = (
        select(CampaignTarget)
        .where(
            CampaignTarget.campaign_id == campaign_id,
            CampaignTarget.tenant_id == current_user.tenant_id,
        )
        .order_by(CampaignTarget.created_at.asc())
    )
    res = await db.execute(stmt)
    targets = list(res.scalars().all())
    return [CampaignTargetResponse.model_validate(t, from_attributes=True) for t in targets]


@router.post(
    "/worker/process",
    summary="Trigger Campaign Worker Batch Process",
    description="Triggers durable campaign target batch processing and dispatching.",
)
async def trigger_worker_batch(
    current_user: User = Depends(require_permission(Permission.TELEPHONY_DISPATCH.value)),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    from app.telephony.worker import CampaignWorkerService
    worker = CampaignWorkerService(db)
    dispatched = await worker.dispatch_pending_targets(batch_size=10)
    return {"status": "ok", "dispatched_count": dispatched}
