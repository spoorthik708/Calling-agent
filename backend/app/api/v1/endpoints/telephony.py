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
