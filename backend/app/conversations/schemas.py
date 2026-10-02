from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationCreateRequest(BaseModel):
    agent_id: uuid.UUID
    external_user_id: Optional[str] = Field(None, max_length=255)
    channel: str = Field("text", max_length=50)
    language: str = Field("en", min_length=2, max_length=10)
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in ("text", "api"):
            raise ValueError("Supported channels for Phase 4 are strictly 'text' and 'api'.")
        return clean


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    external_user_id: Optional[str] = None
    channel: str
    status: str
    language: str
    started_at: datetime
    last_message_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = Field(None, alias="conversation_metadata")
    created_at: datetime
    updated_at: datetime


class MessageCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Message content cannot be blank.")
        return clean


class CitationItem(BaseModel):
    knowledge_base_id: str
    document_id: str
    document_version_id: str
    chunk_id: str
    document_name: str
    page_number: Optional[int] = None
    similarity_score: float


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    sequence_number: int
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    citations: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = Field(None, alias="message_metadata")
    created_at: datetime


class TurnExecutionResponse(BaseModel):
    conversation_id: str
    agent_id: str
    user_message_id: str
    assistant_message_id: str
    user_sequence_number: int
    assistant_sequence_number: int
    content: str
    citations: List[CitationItem] = []
    metadata: Dict[str, Any] = {}
