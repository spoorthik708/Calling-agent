from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ConversationMessage(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    role: MessageRole
    content: str
    language: str = "en"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationSession(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    channel: str = "voice"  # voice, web, phone
    is_active: bool = True
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    messages: List[ConversationMessage] = Field(default_factory=list)


class ConversationManagerInterface(ABC):
    """Interface for managing multi-turn conversation sessions within tenant isolation."""
    @abstractmethod
    async def create_session(
        self,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        channel: str = "voice",
    ) -> ConversationSession:
        pass

    @abstractmethod
    async def append_message(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        message: ConversationMessage,
    ) -> None:
        pass

    @abstractmethod
    async def get_session_history(
        self,
        session_id: uuid.UUID,
        tenant_id: uuid.UUID,
        limit: int = 50,
    ) -> List[ConversationMessage]:
        pass
