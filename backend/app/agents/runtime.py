import re
from typing import Any, Dict, List, Optional
import uuid

from app.agents.ai_provider import AIProviderInterface, AIProviderFactory
from app.agents.interfaces import (
    AgentDecision,
    AgentRuntimeInterface,
    DecisionActionType,
)
from app.core.exceptions import TenantIsolationError
from app.knowledge.interfaces import KnowledgeRetrieverInterface
from app.knowledge.schemas import VerificationStatus, VerifiedKnowledgeItem

# Strict regex detecting factual business inquiries requiring verified grounding
FACTUAL_BUSINESS_KEYWORDS = re.compile(
    r"\b(price|pricing|cost|discount|offer|promo|promotion|referral|fee|refund|"
    r"available|availability|appointment|slot|policy|terms|guarantee|warranty|"
    r"deadline|eligibility|account balance|payment method)\b",
    re.IGNORECASE,
)


class BaseAgentRuntime(AgentRuntimeInterface):
    """
    Foundational Agent Runtime enforcing YAVURA'S Core Product Principle:
    Factual Truth Responsibility belongs to verified business systems, not the LLM.
    """

    def __init__(
        self,
        ai_provider: Optional[AIProviderInterface] = None,
        knowledge_retriever: Optional[KnowledgeRetrieverInterface] = None,
    ):
        self.ai_provider = ai_provider or AIProviderFactory.get_provider("mock")
        self.knowledge_retriever = knowledge_retriever

    async def process_turn(
        self,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID,
        user_utterance: str,
        conversation_history: List[Dict[str, str]],
        language: str = "en",
        **kwargs: Any,
    ) -> AgentDecision:
        if not tenant_id:
            raise TenantIsolationError("Cannot process turn without explicit tenant boundary.")

        # 1. Check if user is asking for factual business information
        is_factual_inquiry = bool(FACTUAL_BUSINESS_KEYWORDS.search(user_utterance))

        verified_context: List[VerifiedKnowledgeItem] = []
        if is_factual_inquiry and self.knowledge_retriever:
            # Query tenant-isolated knowledge store
            retrieved = await self.knowledge_retriever.retrieve(
                query=user_utterance,
                tenant_id=tenant_id,
            )
            # Filter strictly for verified items
            verified_context = [
                item for item in retrieved
                if item.verification_status == VerificationStatus.VERIFIED
            ]

        # 2. CORE PRODUCT PRINCIPLE ENFORCEMENT
        # If user inquires about factual business information, but NO verified knowledge exists:
        # The agent MUST NOT hallucinate or pretend to know. It must clarify or escalate.
        if is_factual_inquiry and not verified_context:
            return AgentDecision(
                action_type=DecisionActionType.ASK_CLARIFICATION,
                response_text=(
                    "I want to make sure I give you exact information, but I cannot verify that specific "
                    "business detail at this moment. Would you like me to connect you with a representative?"
                ),
                factual_grounding_verified=False,
                confidence=1.0,
                escalation_reason="unverified_business_fact_requested",
            )

        # 3. Formulate prompt context with verified items
        context_str = "\n".join([f"- {item.topic}: {item.content}" for item in verified_context])
        system_prompt = (
            f"You are a helpful business conversational agent speaking {language}. "
            "Stick strictly to verified facts provided below. Never invent prices, dates, or policies.\n"
            f"Verified Business Facts:\n{context_str if context_str else 'None'}"
        )

        messages = list(conversation_history)
        messages.append({"role": "user", "content": user_utterance})

        ai_response = await self.ai_provider.generate_response(
            messages=messages,
            system_prompt=system_prompt,
        )

        # 4. Return decision
        if ai_response.tool_calls:
            return AgentDecision(
                action_type=DecisionActionType.CALL_TOOL,
                tool_call=ai_response.tool_calls[0],
                factual_grounding_verified=True,
            )

        return AgentDecision(
            action_type=DecisionActionType.SPEAK,
            response_text=ai_response.content,
            factual_grounding_verified=bool(verified_context) if is_factual_inquiry else True,
            supported_claims=[item.content for item in verified_context],
            confidence=0.95,
        )
