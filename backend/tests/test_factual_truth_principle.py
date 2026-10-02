from typing import List
import uuid
import pytest

from app.agents.interfaces import DecisionActionType
from app.agents.runtime import BaseAgentRuntime
from app.knowledge.interfaces import KnowledgeRetrieverInterface
from app.knowledge.schemas import VerificationStatus, VerifiedKnowledgeItem


class MockKnowledgeRetriever(KnowledgeRetrieverInterface):
    """Retriever returning pre-configured verified knowledge items."""
    def __init__(self, items: List[VerifiedKnowledgeItem]):
        self.items = items

    async def retrieve(
        self,
        query: str,
        tenant_id: uuid.UUID,
        top_k: int = 5,
        min_similarity: float = 0.70,
    ) -> List[VerifiedKnowledgeItem]:
        return [i for i in self.items if i.tenant_id == tenant_id]


@pytest.mark.asyncio
async def test_factual_inquiry_with_unverified_knowledge_escalates():
    """
    CORE PRODUCT PRINCIPLE:
    When a user asks for factual business details (e.g. pricing, discounts, availability)
    and NO verified business information exists, the agent MUST NOT hallucinate or guess.
    It MUST ask for clarification or offer human escalation.
    """
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    
    # Empty knowledge retriever (no verified facts known)
    retriever = MockKnowledgeRetriever([])
    runtime = BaseAgentRuntime(knowledge_retriever=retriever)

    # Customer asks about pricing/discounts
    decision = await runtime.process_turn(
        tenant_id=tenant_id,
        session_id=session_id,
        user_utterance="Can you give me a 50% discount and what is your pricing?",
        conversation_history=[],
    )

    # Must transition to clarification/escalation rather than hallucinating prices
    assert decision.action_type == DecisionActionType.ASK_CLARIFICATION
    assert decision.factual_grounding_verified is False
    assert decision.escalation_reason == "unverified_business_fact_requested"
    assert "cannot verify" in decision.response_text.lower()


@pytest.mark.asyncio
async def test_factual_inquiry_with_verified_knowledge_succeeds():
    """
    When verified business knowledge is available, the agent explains it naturally
    with verified grounding flag set to True.
    """
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()

    verified_item = VerifiedKnowledgeItem(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        topic="Enterprise Pricing",
        content="Enterprise plan is $499 per month billed annually.",
        verification_status=VerificationStatus.VERIFIED,
    )
    retriever = MockKnowledgeRetriever([verified_item])
    runtime = BaseAgentRuntime(knowledge_retriever=retriever)

    decision = await runtime.process_turn(
        tenant_id=tenant_id,
        session_id=session_id,
        user_utterance="What is your enterprise pricing?",
        conversation_history=[],
    )

    assert decision.action_type == DecisionActionType.SPEAK
    assert decision.factual_grounding_verified is True
    assert len(decision.supported_claims) > 0
    assert "Enterprise plan is $499" in decision.supported_claims[0]
