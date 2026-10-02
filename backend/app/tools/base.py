from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type
import uuid
from pydantic import BaseModel, Field


@dataclass
class ToolExecutionContext:
    """Security and tenant execution context passed to any tool invocation."""
    tenant_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None
    user_id: Optional[uuid.UUID] = None
    agent_id: Optional[uuid.UUID] = None
    conversation_id: Optional[uuid.UUID] = None
    message_id: Optional[uuid.UUID] = None
    correlation_id: str = ""
    idempotency_key: Optional[str] = None


@dataclass
class ToolResult:
    """Structured, immutable tool execution result returned to caller and runtime."""
    tool_name: str
    tool_version: str
    success: bool
    data: Any
    error_category: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0
    idempotent_cached: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "success": self.success,
            "data": self.data,
            "error_category": self.error_category,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "idempotent_cached": self.idempotent_cached,
        }


class BaseTool(ABC):
    """
    Base class for all business tools callable by AI agents.
    Every tool must define strict input/output schemas and authorization requirements.
    """
    name: str
    description: str
    version: str = "1.0.0"
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    required_permissions: List[str] = []
    timeout_seconds: float = 10.0
    is_side_effecting: bool = False

    @abstractmethod
    async def execute(
        self,
        arguments: BaseModel,
        context: ToolExecutionContext,
    ) -> BaseModel:
        """Executes the tool with validated arguments within explicit tenant boundary."""
        pass

    def get_declaration(self) -> Dict[str, Any]:
        """Returns JSON schema for AI model function calling registration."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "parameters": self.input_schema.model_json_schema(),
            "timeout_seconds": self.timeout_seconds,
            "is_side_effecting": self.is_side_effecting,
        }


# ==========================================
# Standard Built-in Server-Side Tools
# ==========================================

class LookupCustomerInput(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=50, description="Unique customer identifier")


class LookupCustomerOutput(BaseModel):
    customer_id: str
    status: str
    name: str = "Jane Doe"
    email: str = "jane.doe@example.com"
    tier: str = "Premium"
    account_status: str = "ACTIVE"


class LookupCustomerTool(BaseTool):
    """Internal tool to safely look up customer profiles within tenant boundary."""
    name = "lookup_customer"
    description = "Retrieves customer profile, account standing, and contact details."
    input_schema = LookupCustomerInput
    output_schema = LookupCustomerOutput
    required_permissions = ["tools:execute"]
    timeout_seconds = 5.0
    is_side_effecting = False

    async def execute(
        self,
        arguments: LookupCustomerInput,
        context: ToolExecutionContext,
    ) -> LookupCustomerOutput:
        return LookupCustomerOutput(
            customer_id=arguments.customer_id,
            status=f"Customer {arguments.customer_id} found in tenant {context.tenant_id}",
            name="Jane Doe",
            email=f"{arguments.customer_id.lower()}@customer.example.com",
            tier="Premium",
            account_status="ACTIVE",
        )


class CreateFollowupInput(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=50)
    topic: str = Field(..., min_length=1, max_length=200)
    priority: str = Field(default="medium", pattern="^(low|medium|high|urgent)$")


class CreateFollowupOutput(BaseModel):
    followup_id: str
    customer_id: str
    topic: str
    priority: str
    status: str
    created_at: str


class CreateFollowupTool(BaseTool):
    """Internal side-effecting tool to schedule customer callback or followup task."""
    name = "create_followup"
    description = "Creates a customer support callback or followup task."
    input_schema = CreateFollowupInput
    output_schema = CreateFollowupOutput
    required_permissions = ["tools:execute"]
    timeout_seconds = 8.0
    is_side_effecting = True

    async def execute(
        self,
        arguments: CreateFollowupInput,
        context: ToolExecutionContext,
    ) -> CreateFollowupOutput:
        followup_id = f"fol_{uuid.uuid4().hex[:12]}"
        now_str = datetime.now(timezone.utc).isoformat()
        return CreateFollowupOutput(
            followup_id=followup_id,
            customer_id=arguments.customer_id,
            topic=arguments.topic,
            priority=arguments.priority,
            status="SCHEDULED",
            created_at=now_str,
        )
