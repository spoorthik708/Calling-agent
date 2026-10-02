import asyncio
import uuid
import pytest
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ToolIdempotencyConflictError,
    ToolTimeoutError,
)
from app.models import Agent, Tenant
from app.tools.base import BaseTool, ToolExecutionContext
from app.tools.models import AgentTool, ToolDefinition, ToolExecutionStatus
from app.tools.registry import ToolRegistry
from app.tools.service import ToolExecutionService


class SlowToolInput(BaseModel):
    seconds: float = Field(..., ge=0)


class SlowToolOutput(BaseModel):
    waited: float


class SlowMockTool(BaseTool):
    name = "slow_tool"
    description = "Simulates a long-running external API."
    input_schema = SlowToolInput
    output_schema = SlowToolOutput
    timeout_seconds = 0.5  # 500ms timeout

    async def execute(self, arguments: SlowToolInput, context: ToolExecutionContext) -> SlowToolOutput:
        await asyncio.sleep(arguments.seconds)
        return SlowToolOutput(waited=arguments.seconds)


@pytest.fixture
async def resilience_setup(db_session: AsyncSession):
    tenant = Tenant(
        id=uuid.UUID("77777777-1111-2222-3333-444444444444"),
        name="Resilience Tenant",
        slug="resilience-tenant",
        status="active",
        is_active=True,
    )
    db_session.add(tenant)

    agent = Agent(
        id=uuid.UUID("77777777-0000-0000-0000-000000000001"),
        tenant_id=tenant.id,
        name="Resilience Agent",
        system_prompt="Resilience agent",
        status="active",
    )
    db_session.add(agent)

    # Tool definition for create_followup
    tool_followup = ToolDefinition(
        id=uuid.UUID("77777777-0000-0000-0000-000000000002"),
        tenant_id=tenant.id,
        name="create_followup",
        display_name="Create Followup",
        description="Creates followup ticket.",
        tool_type="internal",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        configuration={},
        is_active=True,
    )
    # Tool definition for slow_tool
    tool_slow = ToolDefinition(
        id=uuid.UUID("77777777-0000-0000-0000-000000000003"),
        tenant_id=tenant.id,
        name="slow_tool",
        display_name="Slow Tool",
        description="Slow mock tool.",
        tool_type="internal",
        input_schema={"type": "object", "properties": {"seconds": {"type": "number"}}},
        output_schema={"type": "object"},
        configuration={"timeout_seconds": 0.5},
        is_active=True,
    )
    db_session.add_all([tool_followup, tool_slow])

    assign1 = AgentTool(tenant_id=tenant.id, agent_id=agent.id, tool_id=tool_followup.id, enabled=True)
    assign2 = AgentTool(tenant_id=tenant.id, agent_id=agent.id, tool_id=tool_slow.id, enabled=True)
    db_session.add_all([assign1, assign2])

    await db_session.commit()

    registry = ToolRegistry(register_builtins=True)
    registry.register(SlowMockTool())

    return {
        "tenant": tenant,
        "agent": agent,
        "tool_followup": tool_followup,
        "tool_slow": tool_slow,
        "registry": registry,
    }


@pytest.mark.asyncio
async def test_tool_idempotency_caching_and_conflict(db_session: AsyncSession, resilience_setup):
    """
    CRITICAL IDEMPOTENCY TEST:
    1. First execution with idempotency_key executes and stores result.
    2. Second execution with identical payload returns cached result (idempotent_cached=True).
    3. Third execution with differing payload raises ToolIdempotencyConflictError.
    """
    tenant = resilience_setup["tenant"]
    agent = resilience_setup["agent"]
    tool_followup = resilience_setup["tool_followup"]
    registry = resilience_setup["registry"]

    service = ToolExecutionService(db_session, registry=registry)
    idem_key = "idemp_test_key_abc_123"

    payload_a = {
        "customer_id": "cust_101",
        "topic": "Refund question",
        "priority": "high",
    }

    # 1. Initial execution
    res1 = await service.execute_tool(
        tenant_id=tenant.id,
        tool_identifier=tool_followup.name,
        arguments=payload_a,
        agent_id=agent.id,
        idempotency_key=idem_key,
    )
    assert res1.success is True
    assert res1.idempotent_cached is False
    initial_followup_id = res1.data["followup_id"]

    # 2. Identical replay -> Cached result returned without re-executing
    res2 = await service.execute_tool(
        tenant_id=tenant.id,
        tool_identifier=tool_followup.name,
        arguments=payload_a,
        agent_id=agent.id,
        idempotency_key=idem_key,
    )
    assert res2.success is True
    assert res2.idempotent_cached is True
    # Side effect was not re-executed: returned the same followup_id
    assert res2.data["followup_id"] == initial_followup_id

    # 3. Differing payload with same key -> Conflict Error!
    payload_b = {
        "customer_id": "cust_101",
        "topic": "Different topic entirely",
        "priority": "low",
    }
    with pytest.raises(ToolIdempotencyConflictError):
        await service.execute_tool(
            tenant_id=tenant.id,
            tool_identifier=tool_followup.name,
            arguments=payload_b,
            agent_id=agent.id,
            idempotency_key=idem_key,
        )


@pytest.mark.asyncio
async def test_tool_timeout_enforced(db_session: AsyncSession, resilience_setup):
    """
    Verifies that a slow tool exceeding timeout is halted and raises ToolTimeoutError.
    """
    tenant = resilience_setup["tenant"]
    agent = resilience_setup["agent"]
    tool_slow = resilience_setup["tool_slow"]
    registry = resilience_setup["registry"]

    service = ToolExecutionService(db_session, registry=registry)

    # Tool timeout is 0.5s, we ask it to wait 2.0s
    with pytest.raises(ToolTimeoutError):
        await service.execute_tool(
            tenant_id=tenant.id,
            tool_identifier=tool_slow.name,
            arguments={"seconds": 2.0},
            agent_id=agent.id,
            timeout_override=0.5,
        )


@pytest.mark.asyncio
async def test_concurrent_duplicate_requests_serialized_safely(db_session: AsyncSession, resilience_setup):
    """
    RACE CONDITION TEST:
    Verifies that when two identical requests arrive concurrently with the same
    idempotency_key, the execution is serialized so only one side effect executes,
    and the second receives the cached result.
    """
    tenant = resilience_setup["tenant"]
    agent = resilience_setup["agent"]
    tool_followup = resilience_setup["tool_followup"]
    registry = resilience_setup["registry"]

    service = ToolExecutionService(db_session, registry=registry)
    idem_key = f"concurrent_race_test_{uuid.uuid4()}"

    payload = {
        "customer_id": "cust_concurrent_99",
        "topic": "Billing inquiry",
        "priority": "medium",
    }

    # Execute two identical requests concurrently
    task1 = asyncio.create_task(
        service.execute_tool(
            tenant_id=tenant.id,
            tool_identifier=tool_followup.name,
            arguments=payload,
            agent_id=agent.id,
            idempotency_key=idem_key,
        )
    )
    task2 = asyncio.create_task(
        service.execute_tool(
            tenant_id=tenant.id,
            tool_identifier=tool_followup.name,
            arguments=payload,
            agent_id=agent.id,
            idempotency_key=idem_key,
        )
    )

    results = await asyncio.gather(task1, task2)
    res_a, res_b = results[0], results[1]

    assert res_a.success is True
    assert res_b.success is True

    # Exactly one executed and the other was returned from idempotency cache
    cached_statuses = [res_a.idempotent_cached, res_b.idempotent_cached]
    assert False in cached_statuses
    assert True in cached_statuses

    # Both must share the EXACT same side-effect result (single ticket created)
    assert res_a.data["followup_id"] == res_b.data["followup_id"]
