from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field

from app.tools.models import ToolType


class ToolDefinitionCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=2, max_length=255)
    description: str = Field(..., min_length=5, max_length=2000)
    tool_type: ToolType = Field(default=ToolType.INTERNAL)
    version: str = Field(default="1.0.0", max_length=20)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    configuration: Dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration dictionary. Plaintext secrets are strictly prohibited.",
    )
    is_active: bool = Field(default=True)


class ToolDefinitionUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    description: Optional[str] = Field(default=None, min_length=5, max_length=2000)
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    configuration: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class ToolDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    display_name: str
    description: str
    tool_type: str
    version: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    configuration: Dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AgentToolAssignRequest(BaseModel):
    tool_id: uuid.UUID
    enabled: bool = Field(default=True)


class AgentToolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    tool_id: uuid.UUID
    enabled: bool
    tool_name: Optional[str] = None
    tool_display_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ToolExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: Optional[uuid.UUID]
    conversation_id: Optional[uuid.UUID]
    message_id: Optional[uuid.UUID]
    tool_id: Optional[uuid.UUID]
    tool_name: str
    tool_version: str
    status: str
    validated_input: Dict[str, Any]
    sanitized_output: Optional[Dict[str, Any]]
    error_category: Optional[str]
    error_message: Optional[str]
    duration_ms: float
    correlation_id: Optional[str]
    idempotency_key: Optional[str]
    created_at: datetime


class ToolDirectExecuteRequest(BaseModel):
    arguments: Dict[str, Any] = Field(default_factory=dict)
    agent_id: Optional[uuid.UUID] = None
    idempotency_key: Optional[str] = None
