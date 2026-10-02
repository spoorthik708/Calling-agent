import uuid
import pytest
from pydantic import BaseModel, Field

from app.core.exceptions import (
    TenantIsolationError,
    ToolExecutionSecurityError,
    ToolNotFoundError,
)
from app.tools.base import BaseTool, ToolExecutionContext
from app.tools.registry import ToolRegistry


class DummyInput(BaseModel):
    customer_id: str = Field(..., max_length=50)


class DummyOutput(BaseModel):
    status: str


class SafeDummyTool(BaseTool):
    name = "lookup_customer"
    description = "Safely looks up a customer profile."
    input_schema = DummyInput
    output_schema = DummyOutput

    async def execute(self, arguments: DummyInput, context: ToolExecutionContext) -> DummyOutput:
        return DummyOutput(status=f"Customer {arguments.customer_id} found")


@pytest.mark.asyncio
async def test_tool_execution_success_with_valid_tenant():
    """Verifies standard valid tool execution inside tenant boundary."""
    registry = ToolRegistry()
    registry.register_tool(SafeDummyTool())

    context = ToolExecutionContext(tenant_id=uuid.uuid4())
    result = await registry.execute_tool(
        tool_name="lookup_customer",
        arguments={"customer_id": "cust_12345"},
        context=context,
    )
    assert result["status"] == "Customer cust_12345 found"


@pytest.mark.asyncio
async def test_tool_execution_fails_without_tenant_context():
    """Verifies that executing a tool without tenant context raises TenantIsolationError."""
    registry = ToolRegistry()
    registry.register_tool(SafeDummyTool())

    context = ToolExecutionContext(tenant_id=None)  # type: ignore
    with pytest.raises(TenantIsolationError):
        await registry.execute_tool(
            tool_name="lookup_customer",
            arguments={"customer_id": "cust_12345"},
            context=context,
        )


@pytest.mark.asyncio
async def test_tool_execution_blocks_prohibited_injection_patterns():
    """
    CRITICAL SECURITY TEST:
    Verifies that malicious payloads containing shell commands, eval, exec, or SQL injections
    are actively rejected by the security validator BEFORE the tool is called.
    """
    registry = ToolRegistry()
    registry.register_tool(SafeDummyTool())
    context = ToolExecutionContext(tenant_id=uuid.uuid4())

    malicious_inputs = [
        {"customer_id": "cust_1; rm -rf /"},
        {"customer_id": "cust_1'; DROP TABLE users; --"},
        {"customer_id": "__import__('os').system('cat /etc/passwd')"},
        {"customer_id": "eval('2+2')"},
        {"customer_id": "powershell -Command Invoke-WebRequest"},
    ]

    for bad_input in malicious_inputs:
        with pytest.raises(ToolExecutionSecurityError):
            await registry.execute_tool(
                tool_name="lookup_customer",
                arguments=bad_input,
                context=context,
            )


@pytest.mark.asyncio
async def test_tool_not_found_raises_error():
    registry = ToolRegistry()
    context = ToolExecutionContext(tenant_id=uuid.uuid4())
    with pytest.raises(ToolNotFoundError):
        await registry.execute_tool(
            tool_name="non_existent_tool",
            arguments={},
            context=context,
        )
