from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentStatus
from app.agents.runtime_service import AgentRuntimeService
from app.auth.dependencies import require_permission
from app.auth.rbac import Permission
from app.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
)
from app.conversations.schemas import (
    ConversationCreateRequest,
    ConversationResponse,
    MessageCreateRequest,
    MessageResponse,
    TurnExecutionResponse,
)
from app.core.exceptions import (
    AgentNotFoundError,
    ConversationNotFoundError,
    EntityNotFoundError,
    IdempotencyConflictError,
    InactiveAgentExecutionError,
    LLMProviderError,
    TenantIsolationError,
    http_exception_from_domain,
)
from app.core.logging import get_logger
from app.database.session import get_db
from app.models.audit import AuditLog
from app.users.models import User

logger = get_logger("yavura.conversations.api")

router = APIRouter(prefix="/conversations", tags=["Conversations & Runtime"])


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Conversation Session",
    description="Initializes a persistent conversation session for an active agent. Requires 'conversations:create'.",
)
async def create_conversation(
    request: ConversationCreateRequest,
    current_user: User = Depends(require_permission(Permission.CONVERSATIONS_CREATE.value)),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    # 1. Verify agent belongs to tenant and is active
    stmt_agent = select(Agent).where(
        Agent.id == request.agent_id,
        Agent.tenant_id == current_user.tenant_id,
    )
    agent = (await db.execute(stmt_agent)).scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found.",
        )
    if agent.status != AgentStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot start conversation with an inactive agent (status: {agent.status}).",
        )

    # 2. Create conversation
    conv = Conversation(
        tenant_id=current_user.tenant_id,
        agent_id=agent.id,
        external_user_id=request.external_user_id,
        channel=request.channel,
        status=ConversationStatus.ACTIVE.value,
        language=request.language or agent.default_language,
        conversation_metadata=request.metadata,
    )
    db.add(conv)
    await db.flush()

    audit = AuditLog(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action="conversation.created",
        resource_type="conversation",
        resource_id=str(conv.id),
        details={"agent_id": str(agent.id), "channel": conv.channel},
    )
    db.add(audit)
    await db.commit()
    await db.refresh(conv)
    return ConversationResponse.model_validate(conv)


@router.get(
    "",
    response_model=List[ConversationResponse],
    status_code=status.HTTP_200_OK,
    summary="List Conversations",
    description="Lists conversation sessions belonging to the authenticated tenant. Requires 'conversations:read'.",
)
async def list_conversations(
    agent_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission(Permission.CONVERSATIONS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[ConversationResponse]:
    stmt = select(Conversation).where(Conversation.tenant_id == current_user.tenant_id)
    if agent_id:
        stmt = stmt.where(Conversation.agent_id == agent_id)
    if status_filter:
        stmt = stmt.where(Conversation.status == status_filter.lower().strip())

    stmt = stmt.order_by(Conversation.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    return [ConversationResponse.model_validate(c) for c in conversations]


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Conversation Metadata",
    description="Retrieves metadata for a specific conversation session. Requires 'conversations:read'.",
)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(require_permission(Permission.CONVERSATIONS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id,
    )
    conv = (await db.execute(stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return ConversationResponse.model_validate(conv)


@router.get(
    "/{conversation_id}/messages",
    response_model=List[MessageResponse],
    status_code=status.HTTP_200_OK,
    summary="List Conversation Messages",
    description="Retrieves paginated turn messages for a conversation session. Requires 'conversations:read'.",
)
async def list_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_permission(Permission.CONVERSATIONS_READ.value)),
    db: AsyncSession = Depends(get_db),
) -> List[MessageResponse]:
    # Verify conversation belongs to tenant
    stmt_conv = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id,
    )
    conv = (await db.execute(stmt_conv)).scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    stmt = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.tenant_id == current_user.tenant_id,
        )
        .order_by(Message.sequence_number.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [MessageResponse.model_validate(m) for m in messages]


@router.post(
    "/{conversation_id}/messages",
    response_model=TurnExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Send Message & Execute Agent Turn",
    description=(
        "Processes a user message turn through the Agent Runtime with verified knowledge grounding. "
        "Supports Idempotency-Key header for duplicate-safe retries. Requires 'agents:run'."
    ),
)
async def execute_conversation_turn(
    conversation_id: uuid.UUID,
    request: MessageCreateRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(require_permission(Permission.AGENTS_RUN.value)),
    db: AsyncSession = Depends(get_db),
) -> TurnExecutionResponse:
    # 1. Fetch conversation to determine agent_id
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.tenant_id == current_user.tenant_id,
    )
    conv = (await db.execute(stmt)).scalar_one_or_none()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )

    # 2. Run Agent Runtime Service
    runtime = AgentRuntimeService(db)
    try:
        response_data = await runtime.execute_turn(
            tenant_id=current_user.tenant_id,
            agent_id=conv.agent_id,
            conversation_id=conversation_id,
            user_message=request.content,
            idempotency_key=idempotency_key,
            actor_id=current_user.id,
        )
        return TurnExecutionResponse.model_validate(response_data)
    except (
        AgentNotFoundError,
        ConversationNotFoundError,
        TenantIsolationError,
        InactiveAgentExecutionError,
        IdempotencyConflictError,
        LLMProviderError,
    ) as e:
        raise http_exception_from_domain(e)
