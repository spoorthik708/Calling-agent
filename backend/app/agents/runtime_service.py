from datetime import datetime, timezone
import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.grounding import GroundedContextBuilder
from app.agents.llm_provider import LLMMessage, LLMProviderFactory, LLMResponse
from app.agents.models import Agent, AgentKnowledgeBase, AgentStatus
from app.agents.tools import global_tool_registry
from app.conversations.memory import ConversationMemoryManager
from app.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    IdempotencyRecord,
    Message,
    MessageRole,
)
from app.core.config import get_settings
from app.core.exceptions import (
    AgentNotFoundError,
    ConversationNotFoundError,
    IdempotencyConflictError,
    InactiveAgentExecutionError,
    LLMProviderError,
    TenantIsolationError,
)
from app.core.logging import get_logger
from app.knowledge.retrieval import RetrievalService
from app.knowledge.schemas import CitationSource, RetrievalResponse, RetrievalStatus
from app.models.audit import AuditLog

logger = get_logger("yavura.agents.runtime")


class AgentRuntimeService:
    """
    Central production execution engine for AI agents and conversation turns.
    Guarantees:
    1. Tenant isolation across Agent, Knowledge Bases, Conversation, and Messages.
    2. Explicit knowledge boundary: ONLY retrieves from explicitly attached KBs.
    3. Grounding invariant: Database/tools control facts; LLM never invents unverified data.
    4. Delimiter sanitization: Untrusted document chunks cannot inject instructions.
    5. Concurrency protection: Locks conversation row (with_for_update) to serialize turns.
    6. Monotonic sequence numbering: Messages strictly increment sequence numbers.
    7. Idempotency: Idempotency-Key guarantees safe retry semantics.
    8. Structured observability: Emits telemetry, token accounting, latency, and audit logs.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.memory_manager = ConversationMemoryManager(
            max_messages=self.settings.MAX_CONVERSATION_HISTORY_MESSAGES,
            max_characters=16000,
        )

    async def execute_turn(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_message: str,
        idempotency_key: Optional[str] = None,
        actor_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """
        Executes a single conversational turn with full grounding, persistence, and auditing.
        """
        turn_start_time = time.perf_counter()
        normalized_content = user_message.strip()

        # 1. Idempotency Check (if key provided)
        if idempotency_key:
            endpoint_name = f"/api/v1/conversations/{conversation_id}/messages"
            req_hash = hashlib.sha256(
                json.dumps({"message": normalized_content}, sort_keys=True).encode("utf-8")
            ).hexdigest()

            stmt_idem = select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.idempotency_key == idempotency_key,
                IdempotencyRecord.endpoint == endpoint_name,
            )
            existing_idem = (await self.db.execute(stmt_idem)).scalar_one_or_none()

            if existing_idem:
                if existing_idem.request_hash == req_hash:
                    logger.info(
                        "Idempotent hit for conversation %s, key=%s",
                        conversation_id,
                        idempotency_key,
                    )
                    return existing_idem.response_body
                else:
                    raise IdempotencyConflictError(
                        message="Idempotency key reused with differing request payload.",
                        details={"idempotency_key": idempotency_key},
                    )

        # 2. Concurrency Control: Acquire conversation with row lock
        dialect_name = self.db.bind.dialect.name if self.db.bind else "postgresql"
        stmt_conv = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
        if dialect_name == "postgresql":
            stmt_conv = stmt_conv.with_for_update()

        conv_result = await self.db.execute(stmt_conv)
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            raise ConversationNotFoundError(
                message=f"Conversation {conversation_id} not found for this tenant.",
                details={"conversation_id": str(conversation_id)},
            )

        # 2b. Concurrency & Idempotency Race Guard:
        # If two identical requests raced before either created an IdempotencyRecord,
        # the second request was blocked on `stmt_conv.with_for_update()`.
        # Now that the first request committed, the second request must re-check IdempotencyRecord
        # while holding the conversation lock, avoiding duplicate execution and IntegrityError.
        if idempotency_key:
            stmt_idem_locked = select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.idempotency_key == idempotency_key,
                IdempotencyRecord.endpoint == endpoint_name,
            )
            locked_idem = (await self.db.execute(stmt_idem_locked)).scalar_one_or_none()
            if locked_idem:
                if locked_idem.request_hash == req_hash:
                    logger.info(
                        "Idempotent post-lock hit for conversation %s, key=%s",
                        conversation_id,
                        idempotency_key,
                    )
                    return locked_idem.response_body
                else:
                    raise IdempotencyConflictError(
                        message="Idempotency key reused with differing request payload.",
                        details={"idempotency_key": idempotency_key},
                    )

        if conversation.agent_id != agent_id:
            raise TenantIsolationError(
                message="Conversation does not belong to the specified agent.",
                details={"conversation_id": str(conversation_id), "agent_id": str(agent_id)},
            )

        if conversation.status not in (ConversationStatus.ACTIVE.value,):
            raise InactiveAgentExecutionError(
                message=f"Cannot execute turn in conversation with status '{conversation.status}'.",
                details={"status": conversation.status},
            )

        # 3. Load Agent and verify active status
        stmt_agent = select(Agent).where(
            Agent.id == agent_id,
            Agent.tenant_id == tenant_id,
        )
        agent = (await self.db.execute(stmt_agent)).scalar_one_or_none()
        if not agent:
            raise AgentNotFoundError(
                message=f"Agent {agent_id} not found for this tenant.",
                details={"agent_id": str(agent_id)},
            )

        if agent.status != AgentStatus.ACTIVE.value:
            raise InactiveAgentExecutionError(
                message=f"Agent '{agent.name}' is {agent.status}. Only ACTIVE agents can process messages.",
                details={"agent_id": str(agent.id), "status": agent.status},
            )

        # 4. Determine next message sequence number
        stmt_seq = select(func.coalesce(func.max(Message.sequence_number), 0)).where(
            Message.conversation_id == conversation.id,
            Message.tenant_id == tenant_id,
        )
        current_max_seq = (await self.db.execute(stmt_seq)).scalar_one()
        user_seq = current_max_seq + 1

        # 5. Persist User Message
        user_msg = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role=MessageRole.USER.value,
            content=normalized_content,
            sequence_number=user_seq,
        )
        self.db.add(user_msg)
        await self.db.flush()

        # 6. Retrieve Knowledge ONLY from explicitly attached Knowledge Bases
        stmt_kb_links = select(AgentKnowledgeBase.knowledge_base_id).where(
            AgentKnowledgeBase.agent_id == agent.id,
            AgentKnowledgeBase.tenant_id == tenant_id,
        )
        attached_kb_ids = (await self.db.execute(stmt_kb_links)).scalars().all()

        retrieval_start = time.perf_counter()
        all_citations: List[CitationSource] = []

        if attached_kb_ids:
            retrieval_service = RetrievalService(self.db)
            for kb_id in attached_kb_ids:
                ret_resp: RetrievalResponse = await retrieval_service.retrieve(
                    tenant_id=tenant_id,
                    knowledge_base_id=kb_id,
                    query=normalized_content,
                )
                # Strict Factual Grounding: LOW_CONFIDENCE and NOT_FOUND results are NOT verified business knowledge
                if ret_resp.status == RetrievalStatus.FOUND and ret_resp.items:
                    all_citations.extend(ret_resp.items)
                elif ret_resp.status == RetrievalStatus.LOW_CONFIDENCE:
                    logger.info(
                        "Retrieval for KB %s returned LOW_CONFIDENCE (%s). Excluding from verified facts.",
                        kb_id,
                        ret_resp.top_similarity,
                    )

            # Sort combined citations by similarity descending
            all_citations.sort(key=lambda c: c.similarity_score, reverse=True)
            # Cap at top 5 citations
            all_citations = all_citations[:5]

        retrieval_latency_ms = (time.perf_counter() - retrieval_start) * 1000.0

        # 7. Fetch bounded conversation history (excluding current user message)
        stmt_history = select(Message).where(
            Message.conversation_id == conversation.id,
            Message.tenant_id == tenant_id,
            Message.sequence_number < user_seq,
        ).order_by(Message.sequence_number.asc())
        history_records = (await self.db.execute(stmt_history)).scalars().all()
        bounded_history = self.memory_manager.select_history(history_records)

        # 8. Build Grounded Model Messages
        llm_messages = GroundedContextBuilder.build_messages(
            agent_system_prompt=agent.system_prompt,
            conversation_language=conversation.language or agent.default_language,
            citations=all_citations,
            history=bounded_history,
            current_user_message=normalized_content,
        )

        # 9. Invoke LLM Provider
        provider = LLMProviderFactory.get_provider(agent.llm_provider)
        llm_start = time.perf_counter()

        try:
            llm_response: LLMResponse = await provider.generate(
                messages=llm_messages,
                model=agent.llm_model,
                temperature=agent.temperature,
                max_output_tokens=agent.max_output_tokens,
            )
            llm_latency_ms = (time.perf_counter() - llm_start) * 1000.0
            assistant_content = llm_response.content.strip()

            # 10. Response Validation
            if not assistant_content:
                logger.warning("LLM provider returned empty response. Applying fallback.")
                assistant_content = agent.fallback_message

        except LLMProviderError as pe:
            logger.error("LLM Provider failure: %s. Using configured fallback.", pe.message)
            llm_latency_ms = (time.perf_counter() - llm_start) * 1000.0
            assistant_content = agent.fallback_message
            llm_response = LLMResponse(
                content=assistant_content,
                provider=agent.llm_provider,
                model=agent.llm_model,
                latency_ms=llm_latency_ms,
            )

        # 11. Format Structured Citations (Tenant-safe, no vectors or secret metadata)
        formatted_citations = [
            {
                "knowledge_base_id": str(c.knowledge_base_id),
                "document_id": str(c.document_id),
                "document_version_id": str(c.document_version_id),
                "chunk_id": str(c.chunk_id),
                "document_name": c.document_name,
                "page_number": c.page_number,
                "similarity_score": c.similarity_score,
            }
            for c in all_citations
        ]

        # 12. Persist Assistant Message
        assistant_seq = user_seq + 1
        now_dt = datetime.now(timezone.utc)

        assistant_msg = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT.value,
            content=assistant_content,
            sequence_number=assistant_seq,
            llm_provider=agent.llm_provider,
            llm_model=agent.llm_model,
            prompt_tokens=llm_response.prompt_tokens,
            completion_tokens=llm_response.completion_tokens,
            latency_ms=llm_response.latency_ms,
            citations=formatted_citations,
            message_metadata={
                "retrieval_latency_ms": round(retrieval_latency_ms, 2),
                "llm_latency_ms": round(llm_latency_ms, 2),
                "citations_count": len(formatted_citations),
            },
        )
        self.db.add(assistant_msg)

        # Update Conversation last_message_at
        conversation.last_message_at = now_dt
        self.db.add(conversation)

        # 13. Audit Event
        audit = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="agent.turn_executed",
            resource_type="conversation",
            resource_id=str(conversation.id),
            details={
                "agent_id": str(agent.id),
                "user_seq": user_seq,
                "assistant_seq": assistant_seq,
                "citations_count": len(formatted_citations),
                "llm_provider": agent.llm_provider,
                "llm_model": agent.llm_model,
            },
        )
        self.db.add(audit)

        # Response Payload
        total_latency_ms = (time.perf_counter() - turn_start_time) * 1000.0
        response_payload = {
            "conversation_id": str(conversation.id),
            "agent_id": str(agent.id),
            "user_message_id": str(user_msg.id),
            "assistant_message_id": str(assistant_msg.id),
            "user_sequence_number": user_seq,
            "assistant_sequence_number": assistant_seq,
            "content": assistant_content,
            "citations": formatted_citations,
            "metadata": {
                "llm_provider": agent.llm_provider,
                "llm_model": agent.llm_model,
                "prompt_tokens": llm_response.prompt_tokens,
                "completion_tokens": llm_response.completion_tokens,
                "retrieval_latency_ms": round(retrieval_latency_ms, 2),
                "llm_latency_ms": round(llm_latency_ms, 2),
                "total_latency_ms": round(total_latency_ms, 2),
            },
        }

        # 14. Persist Idempotency Record (if key provided)
        if idempotency_key:
            expires_at = datetime.fromtimestamp(
                now_dt.timestamp() + (self.settings.CONVERSATION_IDEMPOTENCY_EXPIRE_HOURS * 3600),
                tz=timezone.utc,
            )
            idem_record = IdempotencyRecord(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                endpoint=endpoint_name,
                request_hash=req_hash,
                response_status_code=200,
                response_body=response_payload,
                expires_at=expires_at,
            )
            self.db.add(idem_record)

        await self.db.commit()
        await self.db.refresh(assistant_msg)

        return response_payload
