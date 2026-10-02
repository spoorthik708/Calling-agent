from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel, Field


class CallEventType(str, Enum):
    INCOMING = "incoming"
    ANSWERED = "answered"
    SPEECH_STARTED = "speech_started"
    SPEECH_STOPPED = "speech_stopped"
    BARGE_IN_DETECTED = "barge_in_detected"
    AUDIO_STREAMING = "audio_streaming"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


class CallEvent(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    call_id: str
    tenant_id: uuid.UUID
    event_type: CallEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any] = Field(default_factory=dict)


class AudioChunk(BaseModel):
    """Raw audio frame representation for streaming interfaces."""
    call_id: str
    sequence: int
    payload_bytes: bytes
    sample_rate: int = 16000
    format: str = "pcm_s16le"
