"""Pydantic Schemas for Telephony Endpoints in Phase 7."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, SecretStr, field_validator

from app.telephony.interfaces import CallDirection, CallState


class InboundCallWebhookRequest(BaseModel):
    provider_call_id: str = Field(..., description="Unique provider call identifier (e.g. Twilio CallSid)")
    from_phone: str = Field(..., description="Caller phone number in E.164 format")
    to_phone: str = Field(..., description="Destination phone number in E.164 format")
    agent_id: uuid.UUID = Field(..., description="Target AI agent ID for inbound call handling")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata key-value pairs")


class OutboundCallDispatchResponse(BaseModel):
    call_id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    conversation_id: Optional[uuid.UUID] = None
    voice_session_id: Optional[uuid.UUID] = None
    provider_call_id: str
    direction: str
    from_phone: str
    to_phone: str
    status: str
    created_at: datetime


class CallSessionResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    conversation_id: Optional[uuid.UUID] = None
    voice_session_id: Optional[uuid.UUID] = None
    provider_call_id: str
    telephony_provider: str
    direction: str
    from_phone: str
    to_phone: str
    status: str
    recording_url: Optional[str] = None
    error_message: Optional[str] = None
    duration_seconds: int
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class StatusWebhookPayload(BaseModel):
    provider_call_id: str
    status: str
    error_message: Optional[str] = None
    duration_seconds: Optional[int] = None
    recording_url: Optional[str] = None


class CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    agent_id: uuid.UUID
    from_phone: str
    target_phones: List[str] = Field(..., min_length=1)
    scheduled_at: Optional[datetime] = None
    custom_parameters: Dict[str, Any] = Field(default_factory=dict)


class CampaignResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    from_phone: str
    status: str
    target_phones: List[str]
    completed_count: int
    failed_count: int
    total_count: int
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TelephonyAnalyticsResponse(BaseModel):
    total_calls: int
    inbound_calls: int
    outbound_calls: int
    completed_calls: int
    failed_calls: int
    busy_calls: int
    total_duration_seconds: int
    average_duration_seconds: float
