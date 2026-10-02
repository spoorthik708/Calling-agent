from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field

from app.agents.ai_provider import AIProviderInterface, ToolCall
from app.knowledge.schemas import VerifiedKnowledgeItem


class DecisionActionType(str, Enum):
    SPEAK = "speak"
    CALL_TOOL = "call_tool"
    ASK_CLARIFICATION = "ask_clarification"
    ESCALATE_HUMAN = "escalate_human"


class AgentDecision(BaseModel):
    """Encapsulates the decision made by the agent runtime for a conversational turn."""
    action_type: DecisionActionType
    response_text: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    escalation_reason: Optional[str] = None
    factual_grounding_verified: bool = False
    supported_claims: List[str] = Field(default_factory=list)
    confidence: float = 1.0


class AgentRuntimeInterface(ABC):
    """
    Interface for the modular agent runtime.
    Processes user utterances within conversation context and produces safe, verified decisions.
    """
    @abstractmethod
    async def process_turn(
        self,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        user_utterance: str,
        conversation_history: List[Dict[str, str]],
        language: str = "en",
        **kwargs: Any,
    ) -> AgentDecision:
        """Processes a single conversational turn."""
        pass
