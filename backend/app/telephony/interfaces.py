from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel, Field


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallState(str, Enum):
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    FAILED = "failed"


class InboundCallPayload(BaseModel):
    provider_call_id: str
    from_phone: str
    to_phone: str
    tenant_id: Optional[uuid.UUID] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OutboundCallRequest(BaseModel):
    tenant_id: uuid.UUID
    to_phone: str
    from_phone: str
    agent_id: uuid.UUID
    webhook_url: Optional[str] = None
    custom_parameters: Dict[str, Any] = Field(default_factory=dict)


class TelephonyProviderInterface(ABC):
    """
    Pluggable Telephony Provider Interface.
    Decouples YAVURA from vendor APIs (e.g. Twilio, LiveKit, Vonage, Telnyx, SIP trunks).
    """
    @abstractmethod
    async def initiate_outbound_call(self, request: OutboundCallRequest) -> str:
        """Initiates an outbound call; returns provider_call_id."""
        pass

    @abstractmethod
    async def terminate_call(self, provider_call_id: str) -> bool:
        """Hangs up an active call."""
        pass

    @abstractmethod
    def verify_webhook_signature(
        self,
        payload_body: bytes,
        signature_header: str,
        secret: str,
    ) -> bool:
        """Validates incoming webhook authenticity to prevent spoofed calls."""
        pass
