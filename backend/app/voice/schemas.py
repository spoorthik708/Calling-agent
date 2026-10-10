from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.voice.audio import AudioEncoding
from app.voice.languages import VoiceLanguage, normalize_voice_language
from app.voice.state import VoiceSessionStatus


class VoiceSessionCreateRequest(BaseModel):
    agent_id: uuid.UUID
    conversation_id: Optional[uuid.UUID] = None
    input_language: VoiceLanguage = VoiceLanguage.EN
    output_language: VoiceLanguage = VoiceLanguage.EN
    stt_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    vad_provider: Optional[str] = None
    voice_id: Optional[str] = None
    session_metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_language", "output_language", mode="before")
    @classmethod
    def validate_lang(cls, v: Any) -> VoiceLanguage:
        return normalize_voice_language(v)


class VoiceSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    conversation_id: uuid.UUID
    status: str
    input_language: str
    output_language: str
    stt_provider: str
    tts_provider: str
    vad_provider: str
    voice_id: Optional[str] = None
    current_generation_id: int = 1
    turn_count: int = 0
    interruption_count: int = 0
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    termination_reason: Optional[str] = None
    session_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class VoiceAudioIngestRequest(BaseModel):
    audio_base64: str = Field(..., max_length=2_000_000, description="Base64 encoded audio chunk, bounded to 2MB")
    encoding: AudioEncoding = AudioEncoding.LINEAR16
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    channels: int = Field(default=1, ge=1, le=2)
    bit_depth: int = Field(default=16, ge=8, le=32)


class VoiceAudioIngestResponse(BaseModel):
    session_id: uuid.UUID
    vad_is_speech: bool
    turn_event: Optional[str] = None
    buffer_bytes: int
    queue_size: int


class VoiceTurnRequest(BaseModel):
    text: Optional[str] = Field(default=None, max_length=10_000)
    idempotency_key: Optional[str] = Field(default=None, max_length=255)


class VoiceTurnResponse(BaseModel):
    session_id: uuid.UUID
    turn_id: str
    generation_id: int
    user_transcript: Optional[str] = None
    assistant_text: str
    audio_chunks_count: int
    telemetry: Dict[str, Any] = Field(default_factory=dict)


class VoiceInterruptRequest(BaseModel):
    reason: Optional[str] = "user_barge_in"


class VoiceInterruptResponse(BaseModel):
    session_id: uuid.UUID
    status: str
    interrupted_generation_id: int
    new_generation_id: int
    interruption_count: int


class VoiceSessionEndRequest(BaseModel):
    reason: Optional[str] = "normal_completion"


class VoiceSessionListResponse(BaseModel):
    items: List[VoiceSessionResponse]
    total: int
