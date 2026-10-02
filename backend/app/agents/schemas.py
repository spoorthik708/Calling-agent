from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    system_prompt: str = Field(..., min_length=1, max_length=10000)
    default_language: str = Field("en", min_length=2, max_length=10)
    llm_provider: str = Field("mock", max_length=100)
    llm_model: str = Field("gpt-4o-mini", max_length=100)
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    max_output_tokens: int = Field(1024, ge=16, le=8192)
    fallback_message: str = Field(
        "I'm sorry, I don't have enough verified information to answer that accurately.",
        max_length=1000,
    )
    escalation_enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Agent name cannot be empty.")
        return v


class AgentUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    system_prompt: Optional[str] = Field(None, min_length=1, max_length=10000)
    status: Optional[str] = Field(None, max_length=50)
    default_language: Optional[str] = Field(None, min_length=2, max_length=10)
    llm_provider: Optional[str] = Field(None, max_length=100)
    llm_model: Optional[str] = Field(None, max_length=100)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_output_tokens: Optional[int] = Field(None, ge=16, le=8192)
    fallback_message: Optional[str] = Field(None, max_length=1000)
    escalation_enabled: Optional[bool] = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: Optional[str] = None
    system_prompt: str
    status: str
    default_language: str
    llm_provider: str
    llm_model: str
    temperature: float
    max_output_tokens: int
    fallback_message: str
    escalation_enabled: bool
    created_at: datetime
    updated_at: datetime


class AgentKnowledgeBaseAssociationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
